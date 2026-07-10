"""
FastAPI application — the HTTP layer.

This file only handles web concerns: receiving requests, calling the engine /
stores, and returning responses. All the heavy logic lives in the other modules.

Endpoints:
  GET    /api/health              quick liveness check
  POST   /api/upload              upload & index a PDF or .txt
  POST   /api/ask                 ask a question about the document(s)
  GET    /api/sessions            list this user's chat sessions (sidebar)
  GET    /api/sessions/{id}       full history for one session
  DELETE /api/sessions/{id}       delete a session

Run locally:  uvicorn app.main:app --reload
Interactive docs:  http://localhost:8000/docs
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid

from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Response,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from .config import settings
from .ingest import load_document
from .rag_engine import FALLBACK_MSG, engine
from .schemas import (
    AskRequest,
    AskResponse,
    ChatMessage,
    RenameRequest,
    SessionDetail,
    SessionSummary,
    UploadResponse,
)
from .session_store import store
from .web_tool import search_web, web_enabled

app = FastAPI(title="AI20 Labs — Document Q&A API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ALLOWED_EXT = {".pdf", ".txt"}


def _looks_unanswered(text: str) -> bool:
    """True if the document-based answer is effectively 'I don't know', so we
    know to try the web tool even though some chunks were retrieved."""
    t = text.strip().lower()
    return not t or t.startswith("i could not find") or t == FALLBACK_MSG.lower()


def _stream_words(text: str):
    """Yield a string in small word-sized pieces for a typewriter effect."""
    for part in re.findall(r"\S+\s*", text):
        yield part


def _history_and_prev(user_id: str, session_id: str):
    """Return (history, previous_user_question) for the session's PRIOR turns.
    Call this BEFORE saving the new question. History gives the LLM conversation
    memory; the previous question helps retrieve context for short follow-ups."""
    prior = store.get_session(user_id, session_id)
    history = (
        [{"role": m.role, "content": m.content} for m in prior.messages] if prior else []
    )
    prev_q = next((m["content"] for m in reversed(history) if m["role"] == "user"), None)
    return history, prev_q


# --- Basic user session management (bonus #3) --------------------------------
# We identify each browser with a random id stored in a cookie named "uid".
# It's anonymous (no password), but enough to keep every user's chat sessions
# separate on the server. FastAPI injects this dependency into any route that
# needs the current user.
def current_user(
    response: Response,
    uid: str | None = Cookie(default=None),
    x_user_id: str | None = Header(default=None),
) -> str:
    # Prefer an explicit client-generated id sent as the X-User-Id header. The
    # frontend stores this in localStorage, so it's stable and works reliably
    # across the Vercel <-> EC2 origins (where third-party cookies are flaky).
    if x_user_id:
        return x_user_id
    if not uid:
        uid = uuid.uuid4().hex
        response.set_cookie(
            "uid", uid, max_age=60 * 60 * 24 * 365, samesite="none", secure=True
        )
    return uid


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "llm_configured": bool(settings.groq_api_key),
        "web_tool": web_enabled(),
    }


@app.post("/api/upload", response_model=UploadResponse)
async def upload(
    file: UploadFile = File(...), session_id: str | None = Form(default=None)
) -> UploadResponse:
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, "Only .pdf and .txt files are supported.")

    os.makedirs(settings.upload_dir, exist_ok=True)
    # basename() strips any path components so a crafted filename can't write
    # outside the uploads folder.
    safe_name = os.path.basename(file.filename)
    dest = os.path.join(settings.upload_dir, safe_name)
    with open(dest, "wb") as f:
        f.write(await file.read())

    # Parsing + embedding are CPU-heavy and blocking. Run them in a threadpool
    # so a large PDF doesn't freeze the event loop (which would block every other
    # request — chat, health, etc.) while it's being indexed.
    docs = await run_in_threadpool(load_document, dest)
    n_chunks = await run_in_threadpool(engine.add_documents, docs, session_id)

    return UploadResponse(
        filename=file.filename,
        chunks_indexed=n_chunks,
        message=f"Indexed '{file.filename}' into {n_chunks} chunks.",
    )


@app.post("/api/ask", response_model=AskResponse)
async def ask(body: AskRequest, user_id: str = Depends(current_user)) -> AskResponse:
    # 1) Grab prior history (for memory + follow-up context), then save the new one.
    history, prev_q = _history_and_prev(user_id, body.session_id)
    store.upsert_message(
        user_id, body.session_id, ChatMessage(role="user", content=body.question)
    )

    # 2) Try to answer from THIS chat's document(s), with conversation memory.
    answer, grounded, sources = engine.query(
        body.question,
        session_id=body.session_id,
        last_user_question=prev_q,
        history=history,
    )

    # 3) If the document couldn't answer (nothing retrieved OR the model replied
    #    "not found") and the user allowed web access, try Dappier.
    if (not grounded or _looks_unanswered(answer)) and body.use_web and web_enabled():
        web_answer = search_web(body.question)
        if web_answer:
            answer = engine.summarize_web(body.question, web_answer)
            grounded, sources = False, []

    # 4) Save the assistant's reply and return it.
    store.upsert_message(
        user_id, body.session_id, ChatMessage(role="assistant", content=answer)
    )
    return AskResponse(answer=answer, grounded=grounded, sources=sources)


@app.post("/api/ask/stream")
async def ask_stream(body: AskRequest, user_id: str = Depends(current_user)) -> StreamingResponse:
    """Same as /api/ask, but streams the answer token-by-token as newline-
    delimited JSON (NDJSON). Each line is one of:
      {"type":"meta","grounded":bool,"sources":[...]}
      {"type":"token","text":"..."}
      {"type":"done"}
    """
    history, prev_q = _history_and_prev(user_id, body.session_id)
    store.upsert_message(
        user_id, body.session_id, ChatMessage(role="user", content=body.question)
    )
    web_on = body.use_web and web_enabled()

    def event_stream():
        full = ""

        if web_on:
            # Web toggle ON: resolve the best answer first (document, else web),
            # then stream it word-by-word. We can't stream the raw LLM tokens
            # here because we may need to discard a "not found" doc answer and
            # switch to the web result instead.
            answer, grounded, sources = engine.query(
                body.question,
                session_id=body.session_id,
                last_user_question=prev_q,
                history=history,
            )
            if not grounded or _looks_unanswered(answer):
                web_answer = search_web(body.question)
                if web_answer:
                    answer = engine.summarize_web(body.question, web_answer)
                    grounded, sources = False, []
            yield json.dumps(
                {"type": "meta", "grounded": grounded, "sources": [s.model_dump() for s in sources]}
            ) + "\n"
            for word in _stream_words(answer):
                full += word
                yield json.dumps({"type": "token", "text": word}) + "\n"
                time.sleep(0.015)  # gentle typewriter pacing
        else:
            # Web toggle OFF: stream the real LLM tokens live.
            grounded, sources, token_gen = engine.query_stream(
                body.question,
                session_id=body.session_id,
                last_user_question=prev_q,
                history=history,
            )
            yield json.dumps(
                {"type": "meta", "grounded": grounded, "sources": [s.model_dump() for s in sources]}
            ) + "\n"
            if token_gen is not None:
                for token in token_gen:
                    full += token
                    yield json.dumps({"type": "token", "text": token}) + "\n"
            else:
                full = FALLBACK_MSG
                yield json.dumps({"type": "token", "text": FALLBACK_MSG}) + "\n"

        store.upsert_message(
            user_id, body.session_id, ChatMessage(role="assistant", content=full)
        )
        yield json.dumps({"type": "done"}) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@app.get("/api/sessions", response_model=list[SessionSummary])
def list_sessions(user_id: str = Depends(current_user)) -> list[SessionSummary]:
    return store.list_sessions(user_id)


@app.get("/api/sessions/{session_id}", response_model=SessionDetail)
def get_session(session_id: str, user_id: str = Depends(current_user)) -> SessionDetail:
    detail = store.get_session(user_id, session_id)
    if not detail:
        raise HTTPException(404, "Session not found.")
    return detail


@app.patch("/api/sessions/{session_id}")
def rename_session(
    session_id: str, body: RenameRequest, user_id: str = Depends(current_user)
) -> dict:
    store.rename_session(user_id, session_id, body.title)
    return {"renamed": session_id, "title": body.title}


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str, user_id: str = Depends(current_user)) -> dict:
    store.delete_session(user_id, session_id)
    return {"deleted": session_id}


# End of API routes.
