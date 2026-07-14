import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.memory.embeddings import get_embedder
from app.memory.models import MemoryDocument
from app.memory.service import ingest_document, search_memory
from app.models import User
from app.security import get_current_user

router = APIRouter(prefix="/api/memory", tags=["memory"])


class DocumentIn(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    text: str = Field(min_length=1)


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    source: str
    created_at: datetime


class IngestOut(BaseModel):
    id: uuid.UUID
    name: str
    chunks: int


@router.post("/documents", response_model=IngestOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    body: DocumentIn | None = None,
    file: UploadFile | None = File(default=None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> IngestOut:
    if file is not None:
        raw = await file.read()
        name = file.filename or "documento"
        text = raw.decode("utf-8", "replace")
    elif body is not None:
        name, text = body.name, body.text
    else:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Envía JSON {name,text} o un archivo")

    if not text.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "El documento está vacío")

    document, chunks = await ingest_document(
        db, name=name, source="upload", text=text, embedder=get_embedder()
    )
    return IngestOut(id=document.id, name=document.name, chunks=chunks)


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[MemoryDocument]:
    result = await db.scalars(select(MemoryDocument).order_by(MemoryDocument.created_at.desc()))
    return list(result)


@router.get("/search")
async def search(
    q: str = Query(min_length=1),
    limit: int = Query(default=5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict]:
    return await search_memory(db, query=q, embedder=get_embedder(), limit=limit)
