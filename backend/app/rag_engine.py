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
    def add_documents(self, docs: list[Document]) -> int:
        """Chunk, embed, and store a list of LlamaIndex Documents.

        Returns the number of chunks that were indexed.
        """
        self._lazy_init()
        assert self._index is not None

        nodes = LlamaSettings.node_parser.get_nodes_from_documents(docs)
        self._index.insert_nodes(nodes)
        return len(nodes)

    # ---- QUERYING ----------------------------------------------------------
    def query(self, question: str) -> tuple[str, bool, list[SourceChunk]]:
        """Answer a question from the indexed documents.

        Returns (answer, grounded, sources).
        `grounded` is False when nothing relevant was found — the caller can
        then decide to fall back to the web tool or the "I don't know" message.
        """
        self._lazy_init()
        assert self._index is not None

        # Retrieve the most similar chunks and keep only those above our cutoff.
        retriever = self._index.as_retriever(similarity_top_k=settings.similarity_top_k)
        scored_nodes = retriever.retrieve(question)
        relevant = [n for n in scored_nodes if (n.score or 0) >= settings.similarity_cutoff]

        if not relevant:
            return FALLBACK_MSG, False, []

        sources = [
            SourceChunk(
                text=n.node.get_content()[:400],
                score=round(n.score or 0, 3),
                document=n.node.metadata.get("file_name"),
            )
            for n in relevant
        ]

        # No LLM configured -> return the best chunk verbatim so the app still
        # works end-to-end without an API key (useful while learning).
        if LlamaSettings.llm is None:
            return relevant[0].node.get_content(), True, sources

        synthesizer = get_response_synthesizer(text_qa_template=QA_TEMPLATE)
        response = synthesizer.synthesize(question, nodes=relevant)
        return str(response).strip(), True, sources

    # ---- STREAMING QUERY ---------------------------------------------------
    def query_stream(self, question: str):
        """Like query(), but returns a token generator for streaming answers.

        Returns (grounded, sources, token_gen). When grounded is False the
        token_gen is None and the caller streams the fallback / web answer.
        """
        self._lazy_init()
        assert self._index is not None

        retriever = self._index.as_retriever(similarity_top_k=settings.similarity_top_k)
        scored_nodes = retriever.retrieve(question)
        relevant = [n for n in scored_nodes if (n.score or 0) >= settings.similarity_cutoff]

        if not relevant:
            return False, [], None

        sources = [
            SourceChunk(
                text=n.node.get_content()[:400],
                score=round(n.score or 0, 3),
                document=n.node.metadata.get("file_name"),
            )
            for n in relevant
        ]

        # No LLM -> yield the best chunk as a single "token".
        if LlamaSettings.llm is None:
            text = relevant[0].node.get_content()

            def _one():
                yield text

            return True, sources, _one()

        # streaming=True makes synthesize() return a response whose .response_gen
        # yields the answer token-by-token as the LLM produces it.
        synthesizer = get_response_synthesizer(text_qa_template=QA_TEMPLATE, streaming=True)
        streaming_response = synthesizer.synthesize(question, nodes=relevant)
        return True, sources, streaming_response.response_gen

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
