// The top-level component. It wires the sidebar (chat history + New Chat) to
// the main chat window, holds the uploaded-document + theme state, and handles
// drag-and-drop file uploads over the whole app.

import { useEffect, useRef, useState, type DragEvent } from "react";
import { Sidebar } from "./components/Sidebar";
import { ChatWindow } from "./components/ChatWindow";
import { UploadPanel } from "./components/UploadPanel";
import { useSessions } from "./hooks/useSessions";
import { useTheme } from "./hooks/useTheme";
import { api } from "./api";

export default function App() {
  const {
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
  } = useSessions();

  const { theme, toggle } = useTheme();

  // The active chat's document (per-session, so switching chats updates it).
  const docName = active?.docName ?? null;

  // Upload state is tracked PER session id so an upload in one chat never blocks
  // or bleeds into another chat.
  const [uploadingIds, setUploadingIds] = useState<Set<string>>(() => new Set());
  const [uploadStatusById, setUploadStatusById] = useState<Record<string, string>>({});
  const uploadControllers = useRef<Record<string, AbortController>>({});

  const [useWeb, setUseWeb] = useState(false);
  const [webAvailable, setWebAvailable] = useState(false);
  const [sending, setSending] = useState(false);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    api
      .health()
      .then((h) => setWebAvailable(h.web_tool))
      .catch(() => setWebAvailable(false));
  }, []);

  function setStatus(id: string, msg: string) {
    setUploadStatusById((p) => ({ ...p, [id]: msg }));
  }

  // Shared upload logic used by both the button and drag-and-drop.
  async function handleUpload(file: File) {
    const sessionId = activeId; // capture now; the user may switch chats mid-upload
    const ext = file.name.toLowerCase().slice(file.name.lastIndexOf("."));
    if (![".pdf", ".txt"].includes(ext)) {
      setStatus(sessionId, "Only .pdf and .txt files are supported.");
      return;
    }

    const controller = new AbortController();
    uploadControllers.current[sessionId] = controller;
    setUploadingIds((p) => new Set(p).add(sessionId));
    setStatus(sessionId, `Uploading ${file.name}…`);

    try {
      const res = await api.upload(file, sessionId, controller.signal);
      setStatus(sessionId, res.message);
      setSessionDoc(sessionId, res.filename);
    } catch (err) {
      const isAbort = (err as Error).name === "AbortError";
      setStatus(sessionId, isAbort ? "Upload cancelled." : `Upload failed: ${(err as Error).message}`);
    } finally {
      setUploadingIds((p) => {
        const next = new Set(p);
        next.delete(sessionId);
        return next;
      });
      delete uploadControllers.current[sessionId];
    }
  }

  function cancelUpload() {
    uploadControllers.current[activeId]?.abort();
  }

  async function handleAsk(question: string) {
    // Add the user message and an empty assistant placeholder to fill in as the
    // answer streams in.
    addMessage({ role: "user", content: question, createdAt: new Date().toISOString() });
    addMessage({ role: "assistant", content: "", createdAt: new Date().toISOString() });
    setSending(true);

    let acc = "";
    let errored = false;
    try {
      await api.askStream(activeId, question, useWeb, {
        onMeta: (grounded) => updateLastMessage({ grounded }),
        onToken: (text) => {
          acc += text;
          updateLastMessage({ content: acc });
        },
      });
    } catch (err) {
      errored = true;
      updateLastMessage({
        content: `⚠️ Error contacting the server: ${(err as Error).message}`,
      });
    } finally {
      // Guard against an empty stream leaving the bubble stuck on "typing…".
      if (!errored && !acc.trim()) {
        updateLastMessage({ content: "I could not generate a response. Please try again." });
      }
      setSending(false);
    }
  }

  // --- Drag-and-drop handlers (whole-app drop zone) ---
  function onDragOver(e: DragEvent) {
    e.preventDefault();
    setDragging(true);
  }
  function onDragLeave(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
  }
  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) handleUpload(file);
  }

  return (
    <div className="app" onDragOver={onDragOver} onDragLeave={onDragLeave} onDrop={onDrop}>
      {dragging && (
        <div className="drop-overlay">
          <div className="drop-card">📄 Drop your PDF or .txt to upload</div>
        </div>
      )}

      <Sidebar
        sessions={sessions}
        activeId={activeId}
        onNewChat={newChat}
        onSelect={selectSession}
        onDelete={deleteSession}
        onRename={renameSession}
      />

      <main className="main">
        <header className="topbar">
          <div className="topbar-left">
            <h1>Document Q&amp;A</h1>
            {docName ? (
              <span className="doc-chip" title={docName}>
                <span className="doc-dot" /> {docName}
              </span>
            ) : (
              <p className="subtitle">Upload a PDF or .txt to begin</p>
            )}
          </div>

          <div className="topbar-right">
            <button className="theme-btn" onClick={toggle} title="Toggle light/dark">
              {theme === "dark" ? "☀️" : "🌙"}
            </button>
            <UploadPanel
              busy={uploadingIds.has(activeId)}
              status={uploadStatusById[activeId] ?? ""}
              onFile={handleUpload}
              onCancel={cancelUpload}
            />
          </div>
        </header>

        <ChatWindow
          messages={active?.messages ?? []}
          sending={sending}
          onAsk={handleAsk}
          onClear={clearChat}
          useWeb={useWeb}
          onToggleWeb={setUseWeb}
          webAvailable={webAvailable}
          hasDoc={!!docName}
          docName={docName}
        />
      </main>
    </div>
  );
}
