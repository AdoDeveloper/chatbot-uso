from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_perm
from app.core.permissions import P
from app.db.session import get_db
from app.models.enums import ReviewStatus, SourceStatus
from app.models.source import Source
from app.models.user import User
from app.schemas.common import BulkQueueResult, BulkUploadResult, OperationStatus
from app.schemas.source import SourceResponse, SourceUpdateMeta
from app.services.system import audit as audit_svc
from app.services.sources import service as sources_svc

router = APIRouter(prefix="/sources", tags=["sources"])
log = structlog.get_logger()


@router.get("", response_model=list[SourceResponse])
async def list_sources(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_perm(P.KNOWLEDGE_READ)),
):
    """Lista todas las fuentes activas (no soft-deleted), ordenadas por más reciente.

    Eager-loads las relaciones `created_by` y `reviewed_by` para que el shape de la
    respuesta incluya nombres en lugar de UUIDs sueltos.
    """
    result = await db.execute(
        select(Source)
        .where(Source.deleted_at.is_(None))
        .options(*sources_svc.with_user_options())
        .order_by(Source.created_at.desc())
    )
    return [SourceResponse.from_source(s) for s in result.scalars().all()]


@router.post("/upload", response_model=SourceResponse, status_code=status.HTTP_201_CREATED)
async def upload_source(
    req: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    name: str = Form(default=""),
    description: str = Form(default=""),
    tags: str = Form(default="[]"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_perm(P.KNOWLEDGE_CREATE)),
):
    """Sube un archivo (PDF/DOCX/XLSX) y dispara la ingestión en background."""
    source = await sources_svc.upload_source(
        db, req=req, background_tasks=background_tasks, file=file,
        name=name, description=description, tags=tags, current_user=current_user,
    )
    return SourceResponse.from_source(source)


@router.post("/bulk-upload", response_model=BulkUploadResult, status_code=status.HTTP_201_CREATED)
async def bulk_upload_sources(
    req: Request,
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    tags: str = Form(default="[]"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_perm(P.KNOWLEDGE_CREATE)),
):
    """Sube múltiples archivos y dispara la ingestión de cada uno en background."""
    return await sources_svc.bulk_upload_sources(
        db, req=req, background_tasks=background_tasks, files=files, tags=tags, current_user=current_user,
    )


@router.get("/{source_id}", response_model=SourceResponse)
async def get_source(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_perm(P.KNOWLEDGE_READ)),
):
    source = await sources_svc.get_or_404(db, source_id, load_user=True)
    return SourceResponse.from_source(source)


@router.patch("/{source_id}", response_model=SourceResponse)
async def update_source(
    source_id: uuid.UUID,
    body: SourceUpdateMeta,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_perm(P.KNOWLEDGE_UPDATE)),
):
    source = await sources_svc.get_or_404(db, source_id, load_user=True)

    if body.name is not None:
        source.name = body.name

    current_meta: dict = dict(source.meta or {})
    if body.meta is not None:
        current_meta.update(body.meta)
    if body.description is not None:
        current_meta["description"] = body.description
    if body.tags is not None:
        current_meta["tags"] = body.tags
    source.meta = current_meta

    await db.commit()
    await db.refresh(source)

    result = await db.execute(
        select(Source).where(Source.id == source.id).options(*sources_svc.with_user_options())
    )
    return SourceResponse.from_source(result.scalar_one())


@router.post("/{source_id}/ingest", response_model=SourceResponse)
async def reingest_source(
    source_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_perm(P.KNOWLEDGE_UPDATE)),
):
    source = await sources_svc.get_or_404(db, source_id)
    source.status = SourceStatus.pending
    source.error_message = None
    await db.commit()
    await db.refresh(source)
    background_tasks.add_task(sources_svc.run_ingestion, source.id)

    result = await db.execute(
        select(Source).where(Source.id == source.id).options(*sources_svc.with_user_options())
    )
    return SourceResponse.from_source(result.scalar_one())


class RejectRequest(BaseModel):
    # Sin max_length: el contrato es aceptar y truncar a 500 (límite de la
    # columna rejection_reason), no rechazar con 422.
    reason: str = Field(..., min_length=1)


@router.post("/{source_id}/approve", response_model=SourceResponse)
async def approve_source(
    source_id: uuid.UUID,
    req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_perm(P.KNOWLEDGE_MANAGE)),
):
    """Marca la fuente como aprobada — el chatbot puede usarla en sus respuestas.

    Si la fuente venía de un estado `rechazada` se limpia `rejection_reason`.
    Cada aprobación queda registrada en audit_log con la acción `source.approve`.
    """
    source = await sources_svc.get_or_404(db, source_id, load_user=True)
    source.review_status = ReviewStatus.aprobada
    source.reviewed_at = datetime.now(timezone.utc)
    source.reviewed_by_id = current_user.id
    source.rejection_reason = None
    await audit_svc.log_action(
        db,
        action="source.approve",
        resource_type="source",
        actor_id=current_user.id,
        resource_id=str(source.id),
        meta={"name": source.name},
        ip=req.client.host if req.client else None,
        user_agent=req.headers.get("user-agent"),
    )
    await db.commit()
    result = await db.execute(
        select(Source).where(Source.id == source.id)
        .options(*sources_svc.with_user_options())
        .execution_options(populate_existing=True)
    )
    return SourceResponse.from_source(result.scalar_one())


@router.post("/{source_id}/reject", response_model=SourceResponse)
async def reject_source(
    source_id: uuid.UUID,
    body: RejectRequest,
    req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_perm(P.KNOWLEDGE_MANAGE)),
):
    """Marca la fuente como rechazada con un motivo escrito (truncado a 500 chars).

    El chatbot deja de consultar la fuente inmediatamente. La razón queda visible
    en la UI para que el editor que subió la fuente pueda corregirla y re-subirla.
    """
    source = await sources_svc.get_or_404(db, source_id, load_user=True)
    source.review_status = ReviewStatus.rechazada
    source.reviewed_at = datetime.now(timezone.utc)
    source.reviewed_by_id = current_user.id
    source.rejection_reason = body.reason[:500]
    await audit_svc.log_action(
        db,
        action="source.reject",
        resource_type="source",
        actor_id=current_user.id,
        resource_id=str(source.id),
        meta={"name": source.name, "reason": body.reason[:200]},
        ip=req.client.host if req.client else None,
        user_agent=req.headers.get("user-agent"),
    )
    await db.commit()
    result = await db.execute(
        select(Source).where(Source.id == source.id)
        .options(*sources_svc.with_user_options())
        .execution_options(populate_existing=True)
    )
    return SourceResponse.from_source(result.scalar_one())


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    source_id: uuid.UUID,
    req: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_perm(P.KNOWLEDGE_DELETE)),
):
    await sources_svc.delete_source(db, source_id=source_id, req=req, current_user=current_user)


class BulkSourceIds(BaseModel):
    source_ids: list[uuid.UUID] = Field(..., max_length=200)


class BulkTagRequest(BaseModel):
    source_ids: list[uuid.UUID] = Field(..., max_length=200)
    tags: list[str]
    action: Literal["add", "remove"] = "add"


@router.post("/bulk/delete", status_code=status.HTTP_204_NO_CONTENT)
async def bulk_delete(
    body: BulkSourceIds,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_perm(P.KNOWLEDGE_DELETE)),
):
    await sources_svc.bulk_delete_sources(db, source_ids=list(body.source_ids))


@router.post("/bulk/reingest", response_model=BulkQueueResult)
async def bulk_reingest(
    body: BulkSourceIds,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_perm(P.KNOWLEDGE_UPDATE)),
):
    count = await sources_svc.bulk_reingest_sources(db, source_ids=list(body.source_ids), background=background)
    return BulkQueueResult(queued=count)


@router.post("/bulk/tag", response_model=OperationStatus)
async def bulk_tag(
    body: BulkTagRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_perm(P.KNOWLEDGE_UPDATE)),
):
    ids = list(body.source_ids)
    result = await db.execute(
        select(Source).where(Source.id.in_(ids), Source.deleted_at.is_(None))
    )
    sources = result.scalars().all()
    for source in sources:
        meta = dict(source.meta or {})
        existing_tags = set(meta.get("tags", []))
        if body.action == "add":
            existing_tags.update(body.tags)
        elif body.action == "remove":
            existing_tags -= set(body.tags)
        meta["tags"] = sorted(existing_tags)
        source.meta = meta
    await db.commit()
    return OperationStatus()


@router.get("/{source_id}/preview", response_model=dict)
async def preview_source(
    source_id: uuid.UUID,
    max_chars: int = Query(default=4000, ge=1, le=100_000),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_perm(P.KNOWLEDGE_READ)),
):
    """Devuelve un extracto del contenido sin re-ejecutar ingestión.

    Lee el archivo desde disco (si aún existe) y extrae texto plano.
    """
    source = await sources_svc.get_or_404(db, source_id)
    preview_text = ""
    truncated = False

    if source.file_path:
        p = Path(source.file_path)
        if not p.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="El archivo ya no está disponible en disco.",
            )
        try:
            ext = p.suffix.lower()
            if ext in (".txt", ".md", ".csv"):
                preview_text = p.read_text(encoding="utf-8", errors="replace")
            elif ext == ".pdf":
                from pypdf import PdfReader
                reader = PdfReader(str(p))
                pages = [page.extract_text() or "" for page in reader.pages[:5]]
                preview_text = "\n\n".join(pages)
            elif ext in (".docx",):
                from docx import Document
                doc = Document(str(p))
                preview_text = "\n".join(par.text for par in doc.paragraphs[:200])
            else:
                raise HTTPException(
                    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                    detail=f"Preview no soportado para archivos {ext}.",
                )
        except HTTPException:
            raise
        except Exception as e:
            # Detalle a logs; la excepción cruda puede exponer rutas del servidor
            log.error("source.preview_failed", source_id=str(source_id), error=str(e))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="No se pudo extraer el texto del archivo. Verifique que el documento no esté dañado.",
            )

    if len(preview_text) > max_chars:
        preview_text = preview_text[:max_chars]
        truncated = True

    return {"preview": preview_text, "truncated": truncated}


@router.get("/{source_id}/quality", response_model=dict)
async def quality_report_endpoint(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_perm(P.KNOWLEDGE_READ)),
):
    """Indicadores de calidad/uso de la fuente (chunks, último uso, hits 7d)."""
    from app.services.ingestion.source_quality import quality_report
    return await quality_report(db, source_id)
