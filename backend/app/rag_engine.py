"""
The RAG engine — the "brain" of the app.

RAG = Retrieval-Augmented Generation. The idea, in plain English:

  1. INGEST:   Split an uploaded document into small chunks.
  2. EMBED:    Turn each chunk into a vector (a list of numbers that captures
               its meaning) using a local HuggingFace model.
  3. STORE:    Save those vectors in ChromaDB (our vector database).
  4. RETRIEVE: When a user asks a question, embed the question the same way and
               find the chunks whose vectors are closest to it.
  5. GENERATE: Hand those chunks to the Llama-3 LLM (via Groq) and ask it to
               answer the question using ONLY that context.

LlamaIndex wires steps 1–5 together for us. If none of the retrieved chunks are
similar enough to the question, we DON'T call the LLM to make something up —
we return a clear "I don't know" fallback (an acceptance-criteria requirement).
"""

from __future__ import annotations

import os
from typing import Optional

import chromadb
from chromadb.config import Settings as ChromaClientSettings
from llama_index.core import (
    Document,
    Settings as LlamaSettings,
    StorageContext,
    VectorStoreIndex,
    get_response_synthesizer,
)
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.prompts import PromptTemplate
from llama_index.core.vector_stores import MetadataFilter, MetadataFilters
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.llms.groq import Groq
from llama_index.vector_stores.chroma import ChromaVectorStore

from .config import settings
from .schemas import SourceChunk

# This prompt forces the LLM to stay grounded in the retrieved context and to
# admit when the answer isn't there, instead of hallucinating.
QA_TEMPLATE = PromptTemplate(
    "You are a helpful assistant answering questions about an uploaded document.\n"
    "Use ONLY the context information below to answer.\n"
    "If the answer cannot be found in the context, reply exactly:\n"
    '"I could not find the answer to that in the uploaded document."\n'
    "Do not use outside knowledge.\n"
    "---------------------\n"
    "{context_str}\n"
    "---------------------\n"
    "Question: {query_str}\n"
    "Answer: "
)

FALLBACK_MSG = "I could not find the answer to that in the uploaded document."

# Conversation-aware prompt: lets the agent answer document questions (grounded)
# AND questions about the conversation itself (from history), while still
# refusing to use outside knowledge.
CHAT_PROMPT = (
    "You are an assistant answering questions about a document the user uploaded.\n"
    "Rules:\n"
    "- If the question is about the document's content, answer using ONLY the "
    "document context below. If the answer isn't in the context, reply exactly: "
    f'"{FALLBACK_MSG}"\n'
    "- If the question is about this conversation itself (e.g. what the user asked "
    "earlier), answer from the conversation history.\n"
    "- Never use outside knowledge.\n\n"
    "Conversation history:\n{history}\n\n"
    "Document context:\n{context}\n\n"
    "User question: {question}\n"
    "Answer:"
)


class RAGEngine:
    """Owns the models, the vector index, and the query logic."""

    def __init__(self) -> None:
        self._ready = False
        self._index: Optional[VectorStoreIndex] = None

    def _lazy_init(self) -> None:
        """Load models + open the vector store on first use.

        We do this lazily (not at import time) because loading the embedding
        model takes a few seconds and downloads weights the first time.
        """
        if self._ready:
            return

        os.makedirs(settings.chroma_dir, exist_ok=True)

        # 1) Global LlamaIndex settings: which embedding model + LLM to use, and
        #    how to split documents into chunks.
        LlamaSettings.embed_model = HuggingFaceEmbedding(model_name=settings.embed_model)
        LlamaSettings.llm = (
            Groq(model=settings.llm_model, api_key=settings.groq_api_key)
            if settings.groq_api_key
            else None  # No key? Retrieval still works; generation is disabled.
        )
        LlamaSettings.node_parser = SentenceSplitter(chunk_size=512, chunk_overlap=64)

        # 2) Open a *persistent* ChromaDB on disk and get (or create) a
        #    collection configured to use cosine similarity.
        #    anonymized_telemetry=False silences Chroma's harmless telemetry
        #    error logs so the console stays clean.
        client = chromadb.PersistentClient(
            path=settings.chroma_dir,
            settings=ChromaClientSettings(anonymized_telemetry=False),
        )
        collection = client.get_or_create_collection(
            name="documents", metadata={"hnsw:space": "cosine"}
        )
        vector_store = ChromaVectorStore(chroma_collection=collection)
        storage_context = StorageContext.from_defaults(vector_store=vector_store)

        # 3) Build an index object backed by that existing vector store. If the
        #    store already has vectors (e.g. after a restart), they're reused.
        self._index = VectorStoreIndex.from_vector_store(
            vector_store, storage_context=storage_context
        )
        self._ready = True

    # ---- INGESTION ---------------------------------------------------------
    def add_documents(self, docs: list[Document], session_id: str | None = None) -> int:
        """Chunk, embed, and store a list of LlamaIndex Documents.

        If a session_id is given, every chunk is tagged with it so that queries
        from that chat only ever retrieve *its own* document — this prevents one
        chat's answers from leaking in content uploaded in a different chat.

        Returns the number of chunks that were indexed.
        """
        self._lazy_init()
        assert self._index is not None

        if session_id:
            for d in docs:
                d.metadata["session_id"] = session_id

        nodes = LlamaSettings.node_parser.get_nodes_from_documents(docs)
        self._index.insert_nodes(nodes)
        return len(nodes)

    # ---- HELPERS -----------------------------------------------------------
    def _retriever(self, session_id: str | None):
        """A retriever scoped to one session's documents (if session_id given)."""
        filters = None
        if session_id:
            filters = MetadataFilters(
                filters=[MetadataFilter(key="session_id", value=session_id)]
            )
        return self._index.as_retriever(
            similarity_top_k=settings.similarity_top_k, filters=filters
        )

    @staticmethod
    def _retrieval_text(question: str, last_user_question: str | None) -> str:
        """For short follow-ups (e.g. 'Are you sure?'), prepend the previous
        question so retrieval still finds the relevant document chunks."""
        if last_user_question and len(question.split()) <= 6:
            return f"{last_user_question} {question}"
        return question

    @staticmethod
    def _format_history(history: list[dict] | None) -> str:
        if not history:
            return "(no earlier messages)"
        lines = []
        for m in history[-8:]:  # keep the last few turns
            who = "User" if m.get("role") == "user" else "Assistant"
            lines.append(f"{who}: {m.get('content', '')}")
        return "\n".join(lines)

    def _prepare(self, question, session_id, history, last_user_question):
        """Retrieve document context (scoped to the session) and build the
        conversation-aware prompt. Returns (prompt, relevant_nodes, sources)."""
        retriever = self._retriever(session_id)
        scored = retriever.retrieve(self._retrieval_text(question, last_user_question))
        relevant = [n for n in scored if (n.score or 0) >= settings.similarity_cutoff]
        sources = [
            SourceChunk(
                text=n.node.get_content()[:400],
                score=round(n.score or 0, 3),
                document=n.node.metadata.get("file_name"),
            )
            for n in relevant
        ]
        context = (
            "\n\n---\n\n".join(n.node.get_content() for n in relevant)
            if relevant
            else "(no relevant document content found)"
        )
        prompt = CHAT_PROMPT.format(
            history=self._format_history(history), context=context, question=question
        )
        return prompt, relevant, sources

    # ---- QUERYING ----------------------------------------------------------
    def query(
        self,
        question: str,
        session_id: str | None = None,
        last_user_question: str | None = None,
        history: list[dict] | None = None,
    ) -> tuple[str, bool, list[SourceChunk]]:
        """Answer a question using the document context AND conversation history.

        Returns (answer, grounded, sources). `grounded` is True when the answer
        came from the document (some relevant chunk was found and the model
        didn't reply "not found").
        """
        self._lazy_init()
        prompt, relevant, sources = self._prepare(
            question, session_id, history, last_user_question
        )

        # No LLM configured -> return the best chunk verbatim (learning mode).
        if LlamaSettings.llm is None:
            if relevant:
                return relevant[0].node.get_content(), True, sources
            return FALLBACK_MSG, False, []

        answer = str(LlamaSettings.llm.complete(prompt)).strip()
        grounded = bool(relevant) and not answer.lower().startswith("i could not find")
        return answer, grounded, sources

    # ---- STREAMING QUERY ---------------------------------------------------
    def query_stream(
        self,
        question: str,
        session_id: str | None = None,
        last_user_question: str | None = None,
        history: list[dict] | None = None,
    ):
        """Like query(), but returns (grounded, sources, token_gen) where
        token_gen streams the answer as it's produced."""
        self._lazy_init()
        prompt, relevant, sources = self._prepare(
            question, session_id, history, last_user_question
        )
        grounded = bool(relevant)

        if LlamaSettings.llm is None:
            text = relevant[0].node.get_content() if relevant else FALLBACK_MSG

            def _one():
                yield text

            return grounded, sources, _one()

        def _gen():
            for chunk in LlamaSettings.llm.stream_complete(prompt):
                yield chunk.delta or ""

        return grounded, sources, _gen()

    # ---- WEB ANSWER SUMMARISATION -----------------------------------------
    def summarize_web(self, question: str, web_text: str) -> str:
        """Condense a raw web-search result into a concise, direct answer.

        Dappier returns a large block of text; we ask the LLM to distill it into
        2–3 sentences that actually answer the user's question.
        """
        self._lazy_init()
        if LlamaSettings.llm is None:
            return web_text[:600]

        prompt = (
            "Using only the web search results below, answer the question in 2–3 "
            "clear, factual sentences. Do not add commentary or lists.\n\n"
            f"Question: {question}\n\n"
            f"Web search results:\n{web_text}\n\n"
            "Concise answer:"
        )
        try:
            return str(LlamaSettings.llm.complete(prompt)).strip()
        except Exception:
            return web_text[:600]


# One shared engine for the whole app.
engine = RAGEngine()
