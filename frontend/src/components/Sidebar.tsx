// The left sidebar: the "New Chat" button and the "Chat History" list.
// Each past conversation can be opened, renamed (pencil / double-click), or deleted.

import { useState } from "react";
import type { Session } from "../types";

interface Props {
  sessions: Session[];
  activeId: string;
  onNewChat: () => void;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onRename: (id: string, title: string) => void;
}

export function Sidebar({
  sessions,
  activeId,
  onNewChat,
  onSelect,
  onDelete,
  onRename,
}: Props) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [confirmingId, setConfirmingId] = useState<string | null>(null);

  function startEdit(s: Session) {
    setEditingId(s.id);
    setDraft(s.title);
  }

  function commit() {
    if (editingId) onRename(editingId, draft);
    setEditingId(null);
  }

  return (
    <aside className="sidebar">
      <button className="new-chat" onClick={onNewChat}>
        + New Chat
      </button>

      <div className="history-label">Chat History</div>

      <nav className="history">
        {sessions.length === 0 && <p className="empty">No conversations yet.</p>}
        {sessions.map((s) => (
          <div
            key={s.id}
            className={`history-item ${s.id === activeId ? "active" : ""}`}
            onClick={() => editingId !== s.id && onSelect(s.id)}
          >
            {editingId === s.id ? (
              <input
                className="history-edit"
                autoFocus
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onBlur={commit}
                onClick={(e) => e.stopPropagation()}
                onKeyDown={(e) => {
                  if (e.key === "Enter") commit();
                  if (e.key === "Escape") setEditingId(null);
                }}
              />
            ) : (
              <span
                className="history-title"
                onDoubleClick={(e) => {
                  e.stopPropagation();
                  startEdit(s);
                }}
              >
                {s.title || "New chat"}
              </span>
            )}

            {confirmingId === s.id ? (
              <div className="confirm-actions" onClick={(e) => e.stopPropagation()}>
                <span className="confirm-text">Delete?</span>
                <button
                  className="confirm-yes"
                  title="Confirm delete"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDelete(s.id);
                    setConfirmingId(null);
                  }}
                >
                  ✓
                </button>
                <button
                  className="confirm-no"
                  title="Cancel"
                  onClick={(e) => {
                    e.stopPropagation();
                    setConfirmingId(null);
                  }}
                >
                  ✗
                </button>
              </div>
            ) : (
              editingId !== s.id && (
                <div className="history-actions">
                  <button
                    className="edit-btn"
                    title="Rename conversation"
                    onClick={(e) => {
                      e.stopPropagation();
                      startEdit(s);
                    }}
                  >
                    ✎
                  </button>
                  <button
                    className="delete-btn"
                    title="Delete conversation"
                    onClick={(e) => {
                      e.stopPropagation();
                      setConfirmingId(s.id);
                    }}
                  >
                    ×
                  </button>
                </div>
              )
            )}
          </div>
        ))}
      </nav>

      <div className="sidebar-footer">DocuChat · Document Q&amp;A</div>
    </aside>
  );
}
