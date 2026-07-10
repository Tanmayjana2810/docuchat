# AI20 Labs — Intelligent Document Q&A

A full-stack web app where you **upload a PDF or `.txt`**, then **chat with an AI agent** that answers questions using only that document. If the answer isn't in the document, the agent says so instead of making something up — and can optionally search the web.

Built for the AI20 Labs Software Engineer technical assignment.

- **Frontend:** React + TypeScript (Vite)
- **Backend:** Python + FastAPI
- **RAG orchestration:** LlamaIndex
- **Embeddings:** HuggingFace `bge-small-en-v1.5` (local, free — no OpenAI key required)
- **LLM:** Llama-3 via Groq (free API tier)
- **Vector store:** ChromaDB (persistent, on disk)
- **Bonus:** MongoDB session storage, Dappier web access, cookie-based user sessions, GitHub Actions CI/CD, Docker

---

## Features

**Document Q&A (core)**
- Upload **PDF or `.txt`** files, via a button or **drag-and-drop** anywhere on the page.
- Answers are **grounded strictly in the uploaded document**; if it's not there, the agent clearly says it couldn't find it (no hallucinating).
- **Conversation memory** — handles follow-ups ("are you sure?") and questions about the chat itself ("what did I ask first?").
- **Per-chat document scoping** — each conversation only queries its own uploaded document, so answers never bleed between chats.
- **Streaming answers** — responses appear token-by-token, like ChatGPT.
- **Web search (optional)** — a toggle lets the agent answer beyond the document using the Dappier tool.

**Chat & history management**
- **New Chat**, **Clear Chat**, and full **Chat History** in the sidebar.
- **Rename** any conversation (pencil icon or double-click) and **delete** it (with a confirmation step).
- **Export** a conversation to a Markdown file.
- History **persists across page refreshes** (localStorage) and is also **stored server-side in MongoDB**, so the sidebar is database-backed.

**Interface & polish**
- **Light / dark theme toggle** (remembers your choice).
- **Markdown-formatted** answers with **copy-to-clipboard** buttons and **timestamps**.
- **"Document ready" indicator** showing the active chat's file.
- **Cancellable uploads** with per-chat progress, and non-blocking indexing so a large PDF never freezes the app.
- Clean, responsive UI that works on smaller screens.

---

## Demo

- **Live app (frontend):** https://ai20-document-qa.vercel.app
- **Backend API + docs:** https://tanmayai20qa.duckdns.org/docs
- **Video walkthrough:** https://drive.google.com/file/d/1Pm2zI6HamSBtEjwOY-gqaGOW7SOVqzzT/view?usp=sharing

Deployment at a glance: React + TypeScript frontend on **Vercel** (HTTPS), FastAPI
backend in **Docker on AWS EC2**, fronted by **Caddy** for automatic HTTPS.

---

## How it works (architecture)

```
┌─────────────────────────┐         ┌──────────────────────────────────────────┐
│   React + TypeScript     │  HTTP   │            FastAPI backend                 │
│   (Vercel / Netlify)     │ ──────▶ │                                            │
│                          │         │  /upload ─▶ parse ─▶ chunk ─▶ embed ─▶ ┐   │
│  • New Chat              │         │                                       │   │
│  • Chat History (sidebar)│         │                              ChromaDB ◀┘   │
│  • Clear Chat            │         │                              (vectors)     │
│  • localStorage history  │         │  /ask ─▶ embed question ─▶ retrieve top-k  │
│                          │ ◀────── │         ─▶ Llama-3 (Groq) writes answer    │
└─────────────────────────┘         │         ─▶ fallback if nothing relevant    │
                                     │  /sessions ─▶ MongoDB (per-user history)   │
                                     └──────────────────────────────────────────┘
                                              (Docker on AWS EC2)
```

**RAG in one paragraph:** When you upload a document, the backend splits it into
small chunks, converts each into a vector (an embedding that captures meaning),
and stores those vectors in ChromaDB. When you ask a question, it embeds the
question the same way, finds the closest chunks, and asks Llama-3 to answer using
only those chunks. If no chunk is similar enough (below a similarity cutoff), it
returns a clear "I could not find the answer in the document" message.

---

## Repository structure

```
.
├── backend/                 # Python + FastAPI
│   ├── app/
│   │   ├── main.py          # API routes + cookie user sessions
│   │   ├── config.py        # env-based settings
│   │   ├── schemas.py       # request/response models
│   │   ├── rag_engine.py    # LlamaIndex: embed / store / retrieve / generate
│   │   ├── ingest.py        # PDF + txt parsing
│   │   ├── session_store.py # MongoDB chat sessions (in-memory fallback)
│   │   └── web_tool.py      # Dappier web search (optional)
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
├── frontend/                # React + TypeScript (Vite)
│   ├── src/
│   │   ├── App.tsx
│   │   ├── api.ts           # fetch wrapper for the backend
│   │   ├── types.ts         # shared TS types
│   │   ├── hooks/useSessions.ts   # localStorage persistence + chat actions
│   │   └── components/      # Sidebar, ChatWindow, MessageBubble, UploadPanel
│   └── .env.example
├── .github/workflows/       # CI/CD (backend + frontend)
├── docker-compose.yml       # backend + MongoDB, one command
└── README.md
```

---

## Quick start (local)

### Prerequisites
- Python 3.11+
- Node.js 20+
- A free **Groq API key** → https://console.groq.com/keys (no credit card)
- *(Optional)* Docker, MongoDB, a Dappier key

### 1. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env              # then paste your GROQ_API_KEY into .env
uvicorn app.main:app --reload
```

Backend runs at **http://localhost:8000** — interactive API docs at
**http://localhost:8000/docs**.

> First run downloads the embedding model (~90 MB). It's cached afterwards.
> No Groq key yet? The app still runs and returns the most relevant chunk verbatim.

### 2. Frontend

```bash
cd frontend
npm install
cp .env.example .env              # defaults to http://localhost:8000
npm run dev
```

Open **http://localhost:5173**, upload a PDF/txt, and start asking questions.

### 3. Everything in Docker (backend + MongoDB)

```bash
# create a .env next to docker-compose.yml with GROQ_API_KEY=...
docker compose up --build
```

Then run the frontend with `npm run dev` as above.

---

## Environment variables

### Backend (`backend/.env`)
| Variable | Required | Default | Purpose |
|---|---|---|---|
| `GROQ_API_KEY` | recommended | — | Powers Llama-3 answers (free tier) |
| `LLM_MODEL` | no | `llama-3.3-70b-versatile` | Which Groq model |
| `EMBED_MODEL` | no | `BAAI/bge-small-en-v1.5` | Local embedding model |
| `SIMILARITY_CUTOFF` | no | `0.35` | Below this, question is "not in document" |
| `MONGO_URI` | no | — | Enables server-side session history (else in-memory) |
| `DAPPIER_API_KEY` | no | — | Enables the web-search tool |
| `CORS_ORIGINS` | no | localhost | Allowed frontend origins |
| `DOMAIN` | for HTTPS | — | Domain Caddy fetches the TLS certificate for |

### Frontend (`frontend/.env`)
| Variable | Default | Purpose |
|---|---|---|
| `VITE_API_URL` | `http://localhost:8000` | Backend base URL |

---

## API reference

All requests carry an `X-User-Id` header (a stable id the frontend keeps in
localStorage) so the backend can group each user's server-side sessions.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Liveness + which optional features are on |
| `POST` | `/api/upload` | Upload & index a PDF/txt (multipart `file`, `session_id`) |
| `POST` | `/api/ask` | `{ session_id, question, use_web }` → answer (JSON) |
| `POST` | `/api/ask/stream` | Same, but streams the answer token-by-token (NDJSON) |
| `GET` | `/api/sessions` | List this user's chat sessions |
| `GET` | `/api/sessions/{id}` | Full history of one session |
| `PATCH` | `/api/sessions/{id}` | Rename a session |
| `DELETE` | `/api/sessions/{id}` | Delete a session |

---

## Deployment

### Frontend → Vercel
1. Push this repo to GitHub.
2. On Vercel, "Add New Project" → import the repo → set **Root Directory** to `frontend`.
3. Add env var `VITE_API_URL` = your backend URL (e.g. `http://<ec2-ip>:8000`).
4. Deploy. Vercel auto-runs `npm run build`.

### Backend → AWS EC2 (Docker, HTTPS via Caddy)
The `docker-compose.yml` runs three containers: the **backend**, **MongoDB**, and
**Caddy** (a reverse proxy that auto-provisions a free Let's Encrypt HTTPS
certificate). HTTPS is required because the Vercel frontend is served over HTTPS
and browsers block HTTPS→HTTP ("mixed content") calls.

1. Launch an Ubuntu EC2 instance. In the security group open ports **22** (SSH),
   **80** and **443** (Caddy/HTTPS).
2. Point a free domain at the instance's public IP — e.g. a
   [DuckDNS](https://www.duckdns.org) subdomain like `yourname.duckdns.org`.
3. SSH in and install Docker:
   ```bash
   curl -fsSL https://get.docker.com | sudo sh
   sudo usermod -aG docker $USER && newgrp docker
   ```
4. Clone the repo and create `.env` next to `docker-compose.yml`:
   ```
   GROQ_API_KEY=your_key
   DOMAIN=yourname.duckdns.org
   CORS_ORIGINS=https://<your-vercel-app>.vercel.app
   DAPPIER_API_KEY=your_dappier_key   # optional
   ```
5. `docker compose up --build -d`
6. Backend is live at `https://yourname.duckdns.org`. Set the frontend's
   `VITE_API_URL` to that URL and redeploy the frontend on Vercel.

---

## Feature → requirement mapping

| Assignment requirement | Where it's implemented |
|---|---|
| Upload PDF **and** txt | `ingest.py`, `UploadPanel.tsx` |
| LlamaIndex ingest / chunk / embed / index / query | `rag_engine.py` |
| Embeddings (free alternative to OpenAI) | HuggingFace `bge-small-en-v1.5` |
| Store embeddings in ChromaDB | `rag_engine.py` (`ChromaVectorStore`) |
| Fallback when question is unrelated | grounding check in `rag_engine.py` |
| New Chat / Chat History / Clear Chat | `Sidebar.tsx`, `ChatWindow.tsx`, `useSessions.ts` |
| Persist chat across refresh (localStorage) | `useSessions.ts` |
| TypeScript frontend, Python backend | `frontend/` + `backend/` |
| Docker + EC2 | `Dockerfile`, `docker-compose.yml`, this README |
| **Bonus:** Dappier web tool | `web_tool.py`, web toggle in UI |
| **Bonus:** DB-backed sessions + sidebar | `session_store.py` (MongoDB); sidebar loads from `/api/sessions` |
| **Bonus:** user session management | `X-User-Id` header, resolved in `main.py` |
| **Bonus:** CI/CD | `.github/workflows/` |

**Beyond the brief:** conversation memory (follow-ups + "what did I ask?"),
per-chat document isolation, streaming answers, light/dark theme, markdown
answers, rename/export/delete chats.

---

## Notes & design choices
- **Why free/local embeddings?** No API key, no cost, fully reproducible — and
  the assignment explicitly allows a free alternative to OpenAI.
- **Why Groq?** Free tier, very fast, and it serves the Llama-3 models — a clean
  fit for a LlamaIndex project.
- **Grounding:** the LLM is instructed to answer only from retrieved context, and
  we additionally gate on a similarity score so off-topic questions never reach it.
- **Two layers of history:** localStorage (required, survives refresh) on the
  client, plus MongoDB (bonus) on the server for cross-device session listing.
