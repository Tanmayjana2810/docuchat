// The top-level component. It wires the sidebar (chat history + New Chat) to
// the main chat window, holds the uploaded-document + theme state, and handles
// drag-and-drop file uploads over the whole app.

import { useEffect, useState, type DragEvent } from "react";
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
    addMessage,
  } = useSessions();

  const { theme, toggle } = useTheme();

  const [docName, setDocName] = useState<string | null>(null);
  const [uploadStatus, setUploadStatus] = useState<string>("");
  const [uploading, setUploading] = useState(false);
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

  // Shared upload logic used by both the button and drag-and-drop.
  async function handleUpload(file: File) {
    const ext = file.name.toLowerCase().slice(file.name.lastIndexOf("."));
    if (![".pdf", ".txt"].includes(ext)) {
      setUploadStatus("Only .pdf and .txt files are supported.");
      return;
    }
    setUploading(true);
    setUploadStatus(`Uploading ${file.name}…`);
    try {
      const res = await api.upload(file);
      setUploadStatus(res.message);
      setDocName(res.filename);
    } catch (err) {
      setUploadStatus(`Upload failed: ${(err as Error).message}`);
    } finally {
      setUploading(false);
    }
  }

  async function handleAsk(question: string) {
    addMessage({ role: "user", content: question, createdAt: new Date().toISOString() });
    setSending(true);
    try {
      const res = await api.ask(activeId, question, useWeb);
      addMessage({
        role: "assistant",
        content: res.answer,
        createdAt: new Date().toISOString(),
        grounded: res.grounded,
        sources: res.sources,
      });
    } catch (err) {
      addMessage({
        role: "assistant",
        content: `⚠️ Error contacting the server: ${(err as Error).message}`,
        createdAt: new Date().toISOString(),
      });
    } finally {
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
              busy={uploading}
              status={uploadStatus}
              onFile={handleUpload}
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
