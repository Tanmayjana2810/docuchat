// Shared TypeScript types. These mirror the backend's Pydantic schemas so the
// data shapes match on both sides — this is the "type safety" the assignment asks for.

export type Role = "user" | "assistant";

export interface SourceChunk {
  text: string;
  score: number;
  document?: string;
}

export interface Message {
  role: Role;
  content: string;
  createdAt: string; // ISO timestamp
  grounded?: boolean; // true if the answer came from the document
  sources?: SourceChunk[]; // document snippets the answer was based on
}

export interface Session {
  id: string;
  title: string;
  messages: Message[];
  updatedAt: string;
}

// Shapes returned by the backend's MongoDB-backed session endpoints.
export interface ServerSessionSummary {
  session_id: string;
  title: string;
  updated_at: string;
  message_count: number;
}

export interface ServerSessionDetail {
  session_id: string;
  title: string;
  messages: { role: Role; content: string; created_at: string }[];
}

// Shape of POST /api/ask response
export interface AskResponse {
  answer: string;
  grounded: boolean;
  sources: { text: string; score: number; document?: string }[];
}

// Shape of POST /api/upload response
export interface UploadResponse {
  filename: string;
  chunks_indexed: number;
  message: string;
}
