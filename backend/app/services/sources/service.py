from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import aiofiles
import structlog
from fastapi import BackgroundTasks, HTTPException, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.exceptions import NotFoundError
from app.models.enums import ReviewStatus, SourceStatus, SourceType
from app.models.source import Source
from app.models.user import User
from app.schemas.common import BulkUploadResult
from app.services.ingestion import service as ingestion
from app.services.system import audit as audit_svc

log = structlog.get_logger()

_MIME_MAP: dict[str, SourceType] = {
    "application/pdf": SourceType.pdf,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": SourceType.docx,
    "text/plain": SourceType.txt,
}

_EXT_MAP: dict[str, SourceType] = {
    ".pdf": SourceType.pdf,
    ".docx": SourceType.docx,
    ".txt": SourceType.txt,
}


class _ContentHashLock:
    def __init__(self, content_hash: str):
        self._key = f"upload_hash_lock:{content_hash}"
        self._acquired = False

    async def __aenter__(self) -> bool:
        from app.core import redis as _redis_mod
        try:
            ok = await _redis_mod.get_redis().set(self._key, "1", ex=30, nx=True)
            self._acquired = bool(ok)
        except Exception:
            self._acquired = None  # Redis no disponible: no bloquear el upload
        return self._acquired is not False

    async def __aexit__(self, *exc) -> None:
        if self._acquired:
            from app.core import redis as _redis_mod
            try:
                await _redis_mod.get_redis().delete(self._key)
            except Exception:
                pass


def with_user_options():
    # Carga creator + reviewer de forma eager para que SourceResponse.from_source pueda leer ambos
    return (selectinload(Source.created_by), selectinload(Source.reviewed_by))


def uploads_dir() -> Path:
    p = Path(get_settings().UPLOADS_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p


def detect_type(filename: str, content_type: str) -> SourceType:
    if content_type in _MIME_MAP:
        return _MIME_MAP[content_type]
    ext = Path(filename).suffix.lower()
    if ext in _EXT_MAP:
        return _EXT_MAP[ext]
    raise HTTPException(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        detail=f"Formato no soportado: {filename}. Tipos permitidos: PDF, DOCX, TXT.",
    )


async def get_or_404(db: AsyncSession, source_id: uuid.UUID, *, load_user: bool = False) -> Source:
    q = select(Source).where(Source.id == source_id, Source.deleted_at.is_(None))
    if load_user:
        q = q.options(*with_user_options())
    result = await db.execute(q)
    source = result.scalar_one_or_none()
    if not source:
        raise NotFoundError("Fuente no encontrada")
    return source


async def upload_source(
    db: AsyncSession, *, req: Request, background_tasks: BackgroundTasks,
    file: UploadFile, name: str, description: str, tags: str, current_user: User,
) -> Source:
    """Sube un archivo (PDF/DOCX/TXT) y dispara la ingestión en background.

    El status comienza como `pending` y avanza a `processing` → `ready`/`error`
    conforme el job de fondo (chunking + embedding + upsert Qdrant) progresa.
    """
    source_type = detect_type(file.filename or "", file.content_type or "")
    source_name = name.strip() or Path(file.filename or "archivo").stem

    try:
        tags_list: list[str] = json.loads(tags) if tags.strip() else []
    except (json.JSONDecodeError, ValueError):
        tags_list = [t.strip() for t in tags.split(",") if t.strip()]

    max_mb = get_settings().MAX_SOURCE_UPLOAD_MB
    if file.size is not None and file.size > max_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"El archivo excede el límite de {max_mb} MB.")

    file_id = uuid.uuid4()
    suffix = Path(file.filename or "").suffix or f".{source_type.value}"
    dest = uploads_dir() / f"{file_id}{suffix}"

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="El archivo está vacío.")
    if len(content) > max_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"El archivo excede el límite de {max_mb} MB.")

    from app.services.ingestion.source_quality import file_hash, find_duplicate
    chash = file_hash(content)
    async with _ContentHashLock(chash) as acquired:
        if not acquired:
            raise HTTPException(
                status_code=409,
                detail="Se está procesando otra subida de este mismo archivo. "
                       "Espere unos segundos y vuelva a intentarlo.",
            )
        dup = await find_duplicate(db, chash)
        if dup:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "DUPLICATE_CONTENT",
                    "message": f"Este archivo ya existe como '{dup.name}'.",
                    "existing_id": str(dup.id),
                    "existing_name": dup.name,
                },
            )

        async with aiofiles.open(dest, "wb") as f:
            await f.write(content)

        meta: dict = {"tags": tags_list}
        if description.strip():
            meta["description"] = description.strip()

        source = Source(
            name=source_name,
            type=source_type,
            status=SourceStatus.pending,
            file_path=str(dest),
            file_size=len(content),
            content_hash=chash,
            meta=meta,
            created_by_id=current_user.id,
        )
        db.add(source)
        await db.flush()
        await db.refresh(source)

        await audit_svc.log_action(
            db,
            action="source.upload",
            resource_type="source",
            actor_id=current_user.id,
            resource_id=str(source.id),
            meta={"name": source.name, "type": source.type.value, "size": source.file_size},
            ip=req.client.host if req.client else None,
            user_agent=req.headers.get("user-agent"),
        )
        await db.commit()

    background_tasks.add_task(run_ingestion, source.id)

    result = await db.execute(
        select(Source).where(Source.id == source.id).options(*with_user_options())
    )
    return result.scalar_one()


async def replace_source_file(
    db: AsyncSession, *, source_id: uuid.UUID, req: Request,
    background_tasks: BackgroundTasks, file: UploadFile, current_user: User,
) -> Source:
    """Reemplaza el archivo físico de una fuente existente (ej. tras un
    rechazo por contenido incorrecto) y dispara una nueva ingestión.
    """
    source = await get_or_404(db, source_id)
    if source.status == SourceStatus.processing:
        raise HTTPException(
            status_code=409,
            detail="Esta fuente ya se está procesando. Espera a que termine antes de reemplazar el archivo.",
        )

    source_type = detect_type(file.filename or "", file.content_type or "")
    max_mb = get_settings().MAX_SOURCE_UPLOAD_MB
    if file.size is not None and file.size > max_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"El archivo excede el límite de {max_mb} MB.")

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="El archivo está vacío.")
    if len(content) > max_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"El archivo excede el límite de {max_mb} MB.")

    from app.services.ingestion.source_quality import file_hash, find_duplicate
    chash = file_hash(content)
    async with _ContentHashLock(chash) as acquired:
        if not acquired:
            raise HTTPException(
                status_code=409,
                detail="Se está procesando otra subida de este mismo archivo. "
                       "Espere unos segundos y vuelva a intentarlo.",
            )
        dup = await find_duplicate(db, chash, exclude_id=source.id)
        if dup:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "DUPLICATE_CONTENT",
                    "message": f"Este archivo ya existe como '{dup.name}'.",
                    "existing_id": str(dup.id),
                    "existing_name": dup.name,
                },
            )

        old_path = source.file_path
        file_id = uuid.uuid4()
        suffix = Path(file.filename or "").suffix or f".{source_type.value}"
        dest = uploads_dir() / f"{file_id}{suffix}"
        async with aiofiles.open(dest, "wb") as f:
            await f.write(content)

        source.type = source_type
        source.file_path = str(dest)
        source.file_size = len(content)
        source.content_hash = chash
        source.status = SourceStatus.pending
        source.error_message = None
        source.error_code = None
        source.error_hint = None
        source.review_status = ReviewStatus.pendiente_revision
        source.rejection_reason = None

        await audit_svc.log_action(
            db,
            action="source.replace_file",
            resource_type="source",
            actor_id=current_user.id,
            resource_id=str(source.id),
            meta={"name": source.name, "new_size": source.file_size},
            ip=req.client.host if req.client else None,
            user_agent=req.headers.get("user-agent"),
        )
        await db.commit()
        await db.refresh(source)

    if old_path:
        try:
            Path(old_path).unlink(missing_ok=True)
        except Exception:
            pass

    background_tasks.add_task(run_ingestion, source.id)

    result = await db.execute(
        select(Source).where(Source.id == source.id).options(*with_user_options())
    )
    return result.scalar_one()


async def bulk_upload_sources(
    db: AsyncSession, *, req: Request, background_tasks: BackgroundTasks,
    files: list[UploadFile], tags: str, current_user: User,
) -> BulkUploadResult:
    """Sube múltiples archivos y dispara la ingestión de cada uno en background."""
    from app.services.ingestion.source_quality import file_hash, find_duplicate

    max_mb = get_settings().MAX_SOURCE_UPLOAD_MB
    try:
        tags_list: list[str] = json.loads(tags) if tags.strip() else []
    except (json.JSONDecodeError, ValueError):
        tags_list = [t.strip() for t in tags.split(",") if t.strip()]

    created = []
    errors = []

    for file in files:
        try:
            source_type = detect_type(file.filename or "", file.content_type or "")
            source_name = Path(file.filename or "archivo").stem

            content = await file.read()
            if len(content) == 0:
                errors.append({"name": file.filename, "error": "El archivo está vacío."})
                continue
            if len(content) > max_mb * 1024 * 1024:
                errors.append({"name": file.filename, "error": f"Excede el límite de {max_mb} MB."})
                continue

            chash = file_hash(content)
            async with _ContentHashLock(chash) as acquired:
                if not acquired:
                    errors.append({
                        "name": file.filename,
                        "error": "Otra subida de este mismo archivo está en curso.",
                    })
                    continue
                dup = await find_duplicate(db, chash)
                if dup:
                    errors.append({"name": file.filename, "error": f"Contenido duplicado: '{dup.name}'."})
                    continue

                file_id = uuid.uuid4()
                suffix = Path(file.filename or "").suffix or f".{source_type.value}"
                dest = uploads_dir() / f"{file_id}{suffix}"
                async with aiofiles.open(dest, "wb") as f:
                    await f.write(content)

                source = Source(
                    name=source_name,
                    type=source_type,
                    status=SourceStatus.pending,
                    file_path=str(dest),
                    file_size=len(content),
                    content_hash=chash,
                    meta={"tags": tags_list},
                    created_by_id=current_user.id,
                )
                db.add(source)
                await db.flush()  # assigns source.id without committing

                await audit_svc.log_action(
                    db,
                    action="source.upload",
                    resource_type="source",
                    actor_id=current_user.id,
                    resource_id=str(source.id),
                    meta={"name": source.name, "type": source.type.value, "size": source.file_size},
                    ip=req.client.host if req.client else None,
                    user_agent=req.headers.get("user-agent"),
                )
                await db.commit()
                await db.refresh(source)

            background_tasks.add_task(run_ingestion, source.id)
            created.append({"id": str(source.id), "name": source.name})
        except HTTPException as e:
            detail = e.detail if isinstance(e.detail, str) else str(e.detail)
            errors.append({"name": file.filename or "", "error": detail})
        except Exception as e:
            log.error("source.bulk_upload_error", filename=file.filename, error=str(e))
            errors.append({"name": file.filename or "", "error": "No se pudo procesar el archivo."})

    return BulkUploadResult(created=created, errors=errors)


async def delete_source(db: AsyncSession, *, source_id: uuid.UUID, req: Request, current_user: User) -> None:
    source = await get_or_404(db, source_id)
    source.deleted_at = datetime.now(timezone.utc)
    await audit_svc.log_action(
        db,
        action="source.delete",
        resource_type="source",
        actor_id=current_user.id,
        resource_id=str(source_id),
        meta={"name": source.name},
        ip=req.client.host if req.client else None,
        user_agent=req.headers.get("user-agent"),
    )
    await db.commit()
    from app.services.ai import semantic_cache as cache_svc
    from app.services.ingestion.vector_store import delete_source as qdrant_delete
    try:
        await qdrant_delete(str(source_id))
    except Exception as exc:
        log.warning("sources.vector_cleanup_failed", source_id=str(source_id), error=str(exc))
    try:
        await cache_svc.invalidate_by_source(str(source_id))
    except Exception:
        pass


async def bulk_delete_sources(db: AsyncSession, *, source_ids: list[uuid.UUID]) -> None:
    from app.services.ai import semantic_cache as cache_svc
    from app.services.ingestion.vector_store import delete_source as qdrant_delete
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Source).where(Source.id.in_(source_ids), Source.deleted_at.is_(None))
    )
    sources = result.scalars().all()
    deleted_any = False
    for source in sources:
        source.deleted_at = now
        deleted_any = True
        try:
            await qdrant_delete(str(source.id))
        except Exception as exc:
            log.warning("sources.vector_cleanup_failed", source_id=str(source.id), error=str(exc))
    await db.commit()
    if deleted_any:
        try:
            await cache_svc.invalidate_by_source("bulk")
        except Exception:
            pass


async def bulk_reingest_sources(
    db: AsyncSession, *, source_ids: list[uuid.UUID], background: BackgroundTasks,
) -> int:
    result = await db.execute(
        select(Source).where(Source.id.in_(source_ids), Source.deleted_at.is_(None))
    )
    sources = result.scalars().all()
    count = 0
    for source in sources:
        if source.status != SourceStatus.processing:
            source.status = SourceStatus.pending
            source.error_message = None
            count += 1
            background.add_task(run_ingestion, source.id)
    await db.commit()
    return count


async def _acquire_ingestion_lock(source_id: uuid.UUID) -> bool | None:
    """Lock por source para evitar ingestas concurrentes (doble click, reingest
    + edit simultáneo) que dejarían vectores huérfanos o chunk_count incorrecto.

    Devuelve:
      True  → lock adquirido, proceder.
      False → otra ingesta ya corre para este source, NO proceder.
      None  → Redis no disponible; proceder igualmente (no bloquear ingesta).
    """
    from app.core import redis as _redis_mod
    try:
        ok = await _redis_mod.get_redis().set(
            f"ingestion_lock:{source_id}", "1", ex=1800, nx=True
        )
        return bool(ok)
    except Exception:
        return None


async def _release_ingestion_lock(source_id: uuid.UUID) -> None:
    from app.core import redis as _redis_mod
    try:
        await _redis_mod.get_redis().delete(f"ingestion_lock:{source_id}")
    except Exception:
        pass


async def run_ingestion(source_id: uuid.UUID) -> None:
    import structlog as _structlog

    from app.db.session import AsyncSessionLocal
    _log = _structlog.get_logger()

    lock = await _acquire_ingestion_lock(source_id)
    if lock is False:
        _log.warning("ingestion.already_running", source_id=str(source_id))
        return

    try:
        async with AsyncSessionLocal() as db:
            try:
                result = await db.execute(select(Source).where(Source.id == source_id))
                source = result.scalar_one_or_none()
                if source:
                    await ingestion.ingest(db, source)
            except Exception as exc:
                _log.error("ingestion.background_failed", source_id=str(source_id), error=str(exc))
                # Marca la fuente como error para que el UI muestre el fallo en vez de quedarse colgado.
                try:
                    result2 = await db.execute(select(Source).where(Source.id == source_id))
                    src = result2.scalar_one_or_none()
                    if src:
                        src.status = SourceStatus.error
                        src.error_message = str(exc)[:500]
                        await db.commit()
                except Exception:
                    pass
    finally:
        await _release_ingestion_lock(source_id)
