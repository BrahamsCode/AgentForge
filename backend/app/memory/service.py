"""Operaciones de memoria de largo plazo: ingesta y búsqueda semántica."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.chunking import chunk_text
from app.memory.embeddings import Embedder
from app.memory.models import AgentLearning, MemoryChunk, MemoryDocument

_EMBED_BATCH = 64


async def ingest_document(
    db: AsyncSession, *, name: str, source: str, text: str, embedder: Embedder
) -> tuple[MemoryDocument, int]:
    document = MemoryDocument(name=name, source=source)
    db.add(document)
    await db.flush()

    chunks = chunk_text(text)
    for start in range(0, len(chunks), _EMBED_BATCH):
        batch = chunks[start : start + _EMBED_BATCH]
        vectors = await embedder.embed(batch)
        for offset, (content, vector) in enumerate(zip(batch, vectors)):
            db.add(
                MemoryChunk(
                    document_id=document.id,
                    chunk_index=start + offset,
                    content=content,
                    embedding=vector,
                )
            )
    await db.commit()
    return document, len(chunks)


async def search_memory(
    db: AsyncSession, *, query: str, embedder: Embedder, limit: int = 5
) -> list[dict]:
    [qvec] = await embedder.embed([query])
    distance = MemoryChunk.embedding.cosine_distance(qvec)
    rows = (
        await db.execute(
            select(MemoryChunk, MemoryDocument.name, distance.label("distance"))
            .join(MemoryDocument, MemoryDocument.id == MemoryChunk.document_id)
            .order_by(distance)
            .limit(limit)
        )
    ).all()
    return [
        {
            "content": chunk.content,
            "score": round(1.0 - float(dist), 4),  # similitud coseno
            "document_name": doc_name,
            "chunk_index": chunk.chunk_index,
        }
        for chunk, doc_name, dist in rows
    ]


async def save_learning(
    db: AsyncSession, *, agent_id: uuid.UUID, run_id: uuid.UUID | None, content: str,
    embedder: Embedder,
) -> AgentLearning:
    [vector] = await embedder.embed([content])
    learning = AgentLearning(agent_id=agent_id, run_id=run_id, content=content, embedding=vector)
    db.add(learning)
    await db.commit()
    return learning


async def search_learnings(
    db: AsyncSession, *, agent_id: uuid.UUID, query: str, embedder: Embedder, limit: int = 5
) -> list[dict]:
    [qvec] = await embedder.embed([query])
    distance = AgentLearning.embedding.cosine_distance(qvec)
    rows = (
        await db.execute(
            select(AgentLearning, distance.label("distance"))
            .where(AgentLearning.agent_id == agent_id)
            .order_by(distance)
            .limit(limit)
        )
    ).all()
    return [
        {"content": l.content, "score": round(1.0 - float(dist), 4), "run_id": str(l.run_id)}
        for l, dist in rows
    ]
