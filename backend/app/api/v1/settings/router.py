from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_perm
from app.core.permissions import P
from app.db.session import get_db
from app.models.user import User
from app.schemas.settings import ChatbotSettings, ChatbotSettingsWithWarnings
from app.services.system import settings as settings_service

router = APIRouter(prefix="/settings", tags=["settings"])

_EXPORT_VERSION = "1"


@router.get("", response_model=ChatbotSettings)
async def get_settings(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_perm(P.BOT_SETTINGS_READ)),
):
    return await settings_service.get_settings(db)


def _validate_settings(data: ChatbotSettings) -> list[str]:
    """Return warnings for potentially problematic parameter combinations."""
    warnings = []
    if data.score_threshold > 0.95:
        warnings.append(f"score_threshold ({data.score_threshold}) es muy alto — puede que no se recupere ningún chunk")
    if data.temperature > 1.5:
        warnings.append(f"temperature ({data.temperature}) es muy alta — las respuestas pueden ser incoherentes")
    if data.top_k > 15:
        warnings.append(f"top_k ({data.top_k}) es alto — puede aumentar la latencia y el costo significativamente")
    return warnings


@router.put("", response_model=ChatbotSettingsWithWarnings)
async def update_settings(
    data: ChatbotSettings,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_perm(P.BOT_SETTINGS_UPDATE)),
) -> ChatbotSettingsWithWarnings:
    warnings = _validate_settings(data)
    result = await settings_service.update_settings(db, data, current_user.id)
    return ChatbotSettingsWithWarnings(**result.model_dump(), warnings=warnings)


@router.get("/export")
async def export_settings(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_perm(P.BOT_SETTINGS_READ)),
):
    """Descarga la configuración completa del asistente como JSON."""
    cfg = await settings_service.get_settings(db)
    bundle = {
        "version": _EXPORT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "settings": cfg.model_dump(),
    }
    filename = f"chatbot-settings-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}.json"
    return Response(
        content=json.dumps(bundle, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/import", response_model=ChatbotSettingsWithWarnings)
async def import_settings(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_perm(P.BOT_SETTINGS_UPDATE)),
) -> ChatbotSettingsWithWarnings:
    """Importa configuración desde un archivo JSON exportado previamente."""
    if not file.filename or not file.filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="El archivo debe ser un .json exportado desde este panel.")
    if file.content_type and file.content_type not in ("application/json", "text/plain", "application/octet-stream"):
        raise HTTPException(status_code=415, detail="Tipo de contenido no permitido. Se esperaba application/json.")

    _MAX_IMPORT_BYTES = 1 * 1024 * 1024
    raw = await file.read(_MAX_IMPORT_BYTES + 1)
    if len(raw) > _MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail="El archivo supera el límite de 1 MB.")
    try:
        bundle = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="El archivo no es un JSON válido.")

    if bundle.get("version") != _EXPORT_VERSION:
        raise HTTPException(
            status_code=400,
            detail=f"Versión de exportación no compatible (se esperaba {_EXPORT_VERSION!r}, se recibió {bundle.get('version')!r}).",
        )

    try:
        data = ChatbotSettings(**bundle["settings"])
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Configuración inválida: {exc}")

    warnings = _validate_settings(data)
    result = await settings_service.update_settings(db, data, current_user.id)
    return ChatbotSettingsWithWarnings(**result.model_dump(), warnings=warnings)
