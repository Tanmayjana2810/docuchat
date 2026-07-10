// This hook is the frontend's "state engine". It owns every chat session and
// keeps them in localStorage, so a browser refresh never loses your history
// (a hard requirement of the assignment).
//
// It also exposes the actions the UI needs:
//   newChat()      -> start a fresh conversation
//   clearChat()    -> empty the current conversation ("Clear Chat")
//   deleteSession()-> remove a conversation from history
//   selectSession()-> switch to a past conversation ("Chat History")
//   addMessage()   -> append a message to the active session

import { useCallback, useEffect, useState } from "react";
import type { Message, Session } from "../types";
import { api } from "../api";

const STORAGE_KEY = "ai20_sessions_v1";
const ACTIVE_KEY = "ai20_active_session_v1";

function uid(): string {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

function loadSessions(): Session[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Session[]) : [];
  } catch {
    return [];
  }
}

function freshSession(): Session {
  return { id: uid(), title: "New chat", messages: [], updatedAt: new Date().toISOString() };
}

export function useSessions() {
  const [sessions, setSessions] = useState<Session[]>(() => {
    const existing = loadSessions();
    return existing.length ? existing : [freshSession()];
  });
  const [activeId, setActiveId] = useState<string>(
    () => localStorage.getItem(ACTIVE_KEY) ?? ""
  );

  // Make sure there's always a valid active session.
  useEffect(() => {
    if (!sessions.find((s) => s.id === activeId)) {
      setActiveId(sessions[0]?.id ?? "");
    }
  }, [sessions, activeId]);

  // Persist to localStorage whenever sessions change (this is the "survive a
  // refresh" magic — React state is memory-only, localStorage is on disk).
  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions));
  }, [sessions]);

  useEffect(() => {
    if (activeId) localStorage.setItem(ACTIVE_KEY, activeId);
  }, [activeId]);

  // On startup, pull the user's sessions from the MongoDB-backed API and merge
  // in any that aren't already in localStorage (e.g. from another device). This
  // is what makes the sidebar database-backed. If the API is unreachable, we
  // silently keep the localStorage-only view, so the app never breaks.
  useEffect(() => {
    api
      .listSessions()
      .then((server) => {
        if (!server?.length) return;
        setSessions((prev) => {
          const byId = new Map(prev.map((s) => [s.id, s]));
          for (const ss of server) {
            if (!byId.has(ss.session_id)) {
              byId.set(ss.session_id, {
                id: ss.session_id,
                title: ss.title,
                messages: [],
                updatedAt: ss.updated_at,
              });
            }
          }
          return Array.from(byId.values()).sort((a, b) =>
            a.updatedAt < b.updatedAt ? 1 : -1
          );
        });
      })
      .catch(() => {});
  }, []);

  const active = sessions.find((s) => s.id === activeId) ?? sessions[0];

  const newChat = useCallback(() => {
    const s = freshSession();
    setSessions((prev) => [s, ...prev]);
    setActiveId(s.id);
  }, []);

  const selectSession = useCallback((id: string) => {
    setActiveId(id);
    // If this session has no messages loaded yet (e.g. it came from the server
    // on another device), fetch its full history from the database.
    setSessions((prev) => {
      const s = prev.find((x) => x.id === id);
      if (s && s.messages.length === 0) {
        api
          .getSession(id)
          .then((detail) => {
            if (!detail.messages?.length) return;
            setSessions((cur) =>
              cur.map((x) =>
                x.id === id
                  ? {
                      ...x,
                      title: detail.title || x.title,
                      messages: detail.messages.map((m) => ({
                        role: m.role,
                        content: m.content,
                        createdAt: m.created_at,
                      })),
                    }
                  : x
              )
            );
          })
          .catch(() => {});
      }
      return prev;
    });
  }, []);

  const clearChat = useCallback(() => {
    // "Clear Chat" empties the CURRENT conversation but keeps the session.
    setSessions((prev) =>
      prev.map((s) =>
        s.id === activeId ? { ...s, messages: [], title: "New chat" } : s
      )
    );
  }, [activeId]);

  const deleteSession = useCallback((id: string) => {
    setSessions((prev) => {
      const next = prev.filter((s) => s.id !== id);
      return next.length ? next : [freshSession()];
    });
    api.deleteSessionOnServer(id).catch(() => {});
  }, []);

  const renameSession = useCallback((id: string, title: string) => {
    const clean = title.trim() || "New chat";
    setSessions((prev) => prev.map((s) => (s.id === id ? { ...s, title: clean } : s)));
    api.renameSession(id, clean).catch(() => {});
  }, []);

  // Record which document was uploaded into a specific chat (per-session, and
  // persisted to localStorage so it survives a refresh). Takes an explicit id
  // so an upload that finishes after the user switches chats still tags the
  // correct (original) session.
  const setSessionDoc = useCallback((id: string, docName: string) => {
    setSessions((prev) => prev.map((s) => (s.id === id ? { ...s, docName } : s)));
  }, []);

  const addMessage = useCallback(
    (msg: Message) => {
      setSessions((prev) =>
        prev.map((s) => {
          if (s.id !== activeId) return s;
          // Title the session after the first user question.
          const title =
            s.messages.length === 0 && msg.role === "user"
              ? msg.content.slice(0, 40)
              : s.title;
          return {
            ...s,
            title,
            messages: [...s.messages, msg],
            updatedAt: new Date().toISOString(),
          };
        })
      );
    },
    [activeId]
  );

  // Patch the most recent message of the active session. Used during streaming
  // to grow the assistant's answer token-by-token.
  const updateLastMessage = useCallback(
    (patch: Partial<Message>) => {
      setSessions((prev) =>
        prev.map((s) => {
          if (s.id !== activeId || s.messages.length === 0) return s;
          const messages = [...s.messages];
          messages[messages.length - 1] = { ...messages[messages.length - 1], ...patch };
          return { ...s, messages, updatedAt: new Date().toISOString() };
        })
      );
    },
    [activeId]
  );

  return {
    sessions,
    active,
    activeId,
    newChat,
    selectSession,
    clearChat,
    deleteSession,
    renameSession,
    setSessionDoc,
    addMessage,
    updateLastMessage,
  };
}
