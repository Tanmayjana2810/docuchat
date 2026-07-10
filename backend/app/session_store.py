"""
Bonus feature: persist chat sessions on the server in MongoDB.

The frontend already keeps history in localStorage (a hard requirement), but
storing sessions server-side lets us list every past conversation in a sidebar
and separate them per user. Each *session* is one conversation thread.

If MONGO_URI isn't set, we transparently fall back to an in-memory dict so the
app still runs during local development without a database.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from .config import settings
from .schemas import ChatMessage, SessionDetail, SessionSummary


class _MongoBackend:
    def __init__(self, uri: str, db_name: str) -> None:
        from pymongo import MongoClient

        self._col = MongoClient(uri)[db_name]["sessions"]
        self._col.create_index([("user_id", 1), ("updated_at", -1)])

    def upsert_message(self, user_id, session_id, message: ChatMessage) -> None:
        doc = self._col.find_one({"session_id": session_id, "user_id": user_id})
        msg = message.model_dump()
        if doc is None:
            title = message.content[:48] if message.role == "user" else "New chat"
            self._col.insert_one(
                {
                    "session_id": session_id,
                    "user_id": user_id,
                    "title": title,
                    "messages": [msg],
                    "updated_at": datetime.utcnow(),
                }
            )
        else:
            self._col.update_one(
                {"_id": doc["_id"]},
                {"$push": {"messages": msg}, "$set": {"updated_at": datetime.utcnow()}},
            )

    def list_sessions(self, user_id) -> list[SessionSummary]:
        cursor = self._col.find({"user_id": user_id}).sort("updated_at", -1)
        return [
            SessionSummary(
                session_id=d["session_id"],
                title=d.get("title", "New chat"),
                updated_at=d["updated_at"],
                message_count=len(d.get("messages", [])),
            )
            for d in cursor
        ]

    def get_session(self, user_id, session_id) -> Optional[SessionDetail]:
        d = self._col.find_one({"session_id": session_id, "user_id": user_id})
        if not d:
            return None
        return SessionDetail(
            session_id=d["session_id"],
            title=d.get("title", "New chat"),
            messages=[ChatMessage(**m) for m in d.get("messages", [])],
        )

    def delete_session(self, user_id, session_id) -> None:
        self._col.delete_one({"session_id": session_id, "user_id": user_id})

    def rename_session(self, user_id, session_id, title: str) -> None:
        self._col.update_one(
            {"session_id": session_id, "user_id": user_id}, {"$set": {"title": title}}
        )


class _MemoryBackend:
    """Same interface as _MongoBackend, but stores everything in a dict."""

    def __init__(self) -> None:
        self._store: dict = {}  # (user_id, session_id) -> record

    def upsert_message(self, user_id, session_id, message: ChatMessage) -> None:
        key = (user_id, session_id)
        rec = self._store.get(key)
        if rec is None:
            title = message.content[:48] if message.role == "user" else "New chat"
            self._store[key] = {
                "title": title,
                "messages": [message],
                "updated_at": datetime.utcnow(),
            }
        else:
            rec["messages"].append(message)
            rec["updated_at"] = datetime.utcnow()

    def list_sessions(self, user_id) -> list[SessionSummary]:
        out = []
        for (uid, sid), rec in self._store.items():
            if uid != user_id:
                continue
            out.append(
                SessionSummary(
                    session_id=sid,
                    title=rec["title"],
                    updated_at=rec["updated_at"],
                    message_count=len(rec["messages"]),
                )
            )
        return sorted(out, key=lambda s: s.updated_at, reverse=True)

    def get_session(self, user_id, session_id) -> Optional[SessionDetail]:
        rec = self._store.get((user_id, session_id))
        if not rec:
            return None
        return SessionDetail(
            session_id=session_id, title=rec["title"], messages=rec["messages"]
        )

    def delete_session(self, user_id, session_id) -> None:
        self._store.pop((user_id, session_id), None)

    def rename_session(self, user_id, session_id, title: str) -> None:
        rec = self._store.get((user_id, session_id))
        if rec:
            rec["title"] = title


def _make_backend():
    if settings.mongo_uri:
        try:
            return _MongoBackend(settings.mongo_uri, settings.mongo_db)
        except Exception as exc:
            print(f"[session_store] Mongo unavailable ({exc}); using in-memory store.")
    return _MemoryBackend()


store = _make_backend()
