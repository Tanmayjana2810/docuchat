// Thin wrapper around fetch() for talking to the FastAPI backend.
// The base URL is read from an env var so we can point at localhost in dev and
// at the AWS EC2 URL in production without changing code.

import type {
  AskResponse,
  ServerSessionDetail,
  ServerSessionSummary,
  UploadResponse,
} from "./types";

const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

// `credentials: "include"` sends the "uid" cookie so the backend can keep each
// user's server-side sessions separate.
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { credentials: "include", ...init });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string; web_tool: boolean }>("/api/health"),

  upload: (file: File, sessionId: string): Promise<UploadResponse> => {
    const form = new FormData();
    form.append("file", file);
    form.append("session_id", sessionId); // scope the doc to this chat
    return request<UploadResponse>("/api/upload", { method: "POST", body: form });
  },

  ask: (sessionId: string, question: string, useWeb: boolean): Promise<AskResponse> =>
    request<AskResponse>("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, question, use_web: useWeb }),
    }),

  // Streaming version: reads the NDJSON stream and fires callbacks as tokens
  // arrive, so the UI can render the answer word-by-word like ChatGPT.
  askStream: async (
    sessionId: string,
    question: string,
    useWeb: boolean,
    handlers: {
      onMeta?: (grounded: boolean, sources: unknown[]) => void;
      onToken?: (text: string) => void;
      onDone?: () => void;
    }
  ): Promise<void> => {
    const res = await fetch(`${BASE}/api/ask/stream`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, question, use_web: useWeb }),
    });
    if (!res.ok || !res.body) throw new Error(`${res.status}: ${await res.text()}`);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    // Read chunks, split on newlines, and parse each NDJSON line.
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let nl: number;
      while ((nl = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, nl).trim();
        buffer = buffer.slice(nl + 1);
        if (!line) continue;
        const evt = JSON.parse(line);
        if (evt.type === "meta") handlers.onMeta?.(evt.grounded, evt.sources);
        else if (evt.type === "token") handlers.onToken?.(evt.text);
        else if (evt.type === "done") handlers.onDone?.();
      }
    }
  },

  // --- MongoDB-backed session endpoints (bonus) ---
  listSessions: (): Promise<ServerSessionSummary[]> =>
    request<ServerSessionSummary[]>("/api/sessions"),

  getSession: (id: string): Promise<ServerSessionDetail> =>
    request<ServerSessionDetail>(`/api/sessions/${id}`),

  renameSession: (id: string, title: string): Promise<unknown> =>
    request(`/api/sessions/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    }),

  deleteSessionOnServer: (id: string): Promise<unknown> =>
    request(`/api/sessions/${id}`, { method: "DELETE" }),
};
