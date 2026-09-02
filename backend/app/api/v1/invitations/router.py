from __future__ import annotations

import datetime
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_client_ip, require_perm
from app.core.exceptions import NotFoundError
from app.core.permissions import P
from app.core.rate_limit import RateLimitExceeded, check_rate_limit
from app.db.session import get_db
from app.models.invitation import Invitation
from app.models.user import User
from app.schemas.auth import TokenResponse, UserResponse
from app.schemas.invitation import (
    InvitationAcceptRequest,
    InvitationCreate,
    InvitationPublicResponse,
    InvitationResponse,
)
from app.services.system import rbac as rbac_service
from app.services.users import invitation as invitation_service
from app.services.users import service as user_service

log = structlog.get_logger()
router = APIRouter(tags=["invitations"])


def _build_response(inv, request: Request | None = None) -> InvitationResponse:
    data = InvitationResponse.model_validate(inv)
    if request:
        base = str(request.base_url).rstrip("/")
        data.invite_url = f"{base}/api/v1/auth/invite/{inv.token}"
    return data


@router.get("/users/invitations", response_model=dict)
async def list_invitations(
    active_only: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_perm(P.USERS_MANAGE)),
):
    invs, total = await invitation_service.list_invitations(
        db, active_only=active_only, page=page, page_size=page_size
    )
    items = [_build_response(inv, request).model_dump(mode="json") for inv in invs]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


_ROLE_LABELS = {"admin": "Administrador", "editor": "Editor", "viewer": "Consultor"}


async def _send_invitation_email_for(inv: Invitation, invited_by: User) -> bool:
    email_sent = False
    try:
        from app.core.config import get_settings
        from app.services.notifications.smtp import send_invitation_email
        frontend = get_settings().FRONTEND_URL.rstrip("/")
        invite_url = f"{frontend}/invite/{inv.token}"
        email_sent = await send_invitation_email(
            to=inv.email,
            role=_ROLE_LABELS.get(str(getattr(inv.role, "value", inv.role)), str(inv.role)),
            invite_url=invite_url,
            invited_by=invited_by.full_name,
        )
        if not email_sent:
            log.warning("invitation.email_not_sent", email=inv.email)
    except Exception as exc:
        log.warning("invitation.email_failed", email=inv.email, error=str(exc))
    return email_sent


@router.post("/users/invitations", response_model=InvitationResponse, status_code=status.HTTP_201_CREATED)
async def create_invitation(
    body: InvitationCreate,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_perm(P.USERS_MANAGE)),
):
    inv = await invitation_service.create_invitation(
        db,
        email=body.email,
        role=body.role,
        created_by=current_user,
        expires_in_days=body.expires_in_days,
    )
    await db.commit()
    await db.refresh(inv)

    email_sent = await _send_invitation_email_for(inv, current_user)

    response = _build_response(inv, request)
    response.email_sent = email_sent
    return response


@router.post("/users/invitations/{invitation_id}/resend", response_model=InvitationResponse)
async def resend_invitation(
    invitation_id: uuid.UUID,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_perm(P.USERS_MANAGE)),
):
    inv = await db.get(Invitation, invitation_id)
    if not inv:
        raise NotFoundError("Invitación no encontrada")
    inv = await invitation_service.resend_invitation(db, inv)
    await db.commit()
    await db.refresh(inv)

    email_sent = await _send_invitation_email_for(inv, current_user)

    response = _build_response(inv, request)
    response.email_sent = email_sent
    return response


@router.delete("/users/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invitation(
    invitation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_perm(P.USERS_MANAGE)),
):
    result = await db.get(Invitation, invitation_id)
    if not result:
        raise NotFoundError("Invitación no encontrada")
    await invitation_service.revoke_invitation(db, result)
    await db.commit()


@router.delete("/users/invitations/{invitation_id}/permanent", status_code=status.HTTP_204_NO_CONTENT)
async def delete_invitation(
    invitation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_perm(P.USERS_MANAGE)),
):
    result = await db.get(Invitation, invitation_id)
    if not result:
        raise NotFoundError("Invitación no encontrada")
    await invitation_service.delete_invitation(db, result)
    await db.commit()


@router.get("/auth/invite/{token}", response_model=InvitationPublicResponse)
async def get_invitation_info(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Devuelve los datos públicos del token para mostrar en el formulario de registro.

    El token tiene entropía suficiente (secrets.token_urlsafe(48)) para que
    la fuerza bruta sea impráctica de por sí, pero se agrega rate limit como
    defensa en profundidad - el mismo patrón que ya protege accept_invitation.
    """
    client_ip = get_client_ip(request)
    try:
        await check_rate_limit("invite:info", client_ip, max_requests=20, window_seconds=60)
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos. Espere un momento y vuelva a intentarlo.",
            headers={"Retry-After": str(exc.retry_after)},
        )

    inv = await invitation_service.get_by_token(db, token)
    if not inv:
        raise NotFoundError("Invitación no encontrada")
    return InvitationPublicResponse(
        email=inv.email,
        role=inv.role,
        expires_at=inv.expires_at,
        is_usable=inv.is_usable,
    )


@router.post("/auth/invite/{token}/accept", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def accept_invitation(
    token: str,
    body: InvitationAcceptRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    client_ip = get_client_ip(request)
    try:
        await check_rate_limit("invite:accept", client_ip, max_requests=5, window_seconds=60)
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos. Espere un momento y vuelva a intentarlo.",
            headers={"Retry-After": str(exc.retry_after)},
        )

    inv = await invitation_service.get_by_token(db, token)
    if not inv:
        raise NotFoundError("Invitación no encontrada")
    if not inv.is_usable:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La invitación expiró, ya fue usada o está revocada",
        )

    existing = await user_service.get_by_email(db, inv.email)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El correo ya tiene cuenta")

    user = await invitation_service.accept_invitation(
        db, inv, full_name=body.full_name, password=body.password
    )
    user.last_login_at = datetime.datetime.now(datetime.timezone.utc)
    await db.commit()
    await db.refresh(user)

    access, refresh = await rbac_service.issue_user_tokens(db, user)
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        user=UserResponse.model_validate(user),
    )
