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

  const active = sessions.find((s) => s.id === activeId) ?? sessions[0];

  const newChat = useCallback(() => {
    const s = freshSession();
    setSessions((prev) => [s, ...prev]);
    setActiveId(s.id);
  }, []);

  const selectSession = useCallback((id: string) => setActiveId(id), []);

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
  }, []);

  const renameSession = useCallback((id: string, title: string) => {
    const clean = title.trim() || "New chat";
    setSessions((prev) => prev.map((s) => (s.id === id ? { ...s, title: clean } : s)));
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

  return {
    sessions,
    active,
    activeId,
    newChat,
    selectSession,
    clearChat,
    deleteSession,
    renameSession,
    addMessage,
  };
}
