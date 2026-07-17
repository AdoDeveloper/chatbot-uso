from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_perm
from app.core.exceptions import NotFoundError
from app.core.permissions import P
from app.db.session import get_db
from app.models.user import User
from app.schemas.faq import FAQCreate, FAQOut, FAQUpdate
from app.services.knowledge import faq as svc

router = APIRouter(prefix="/faq", tags=["faq"])


@router.get("", response_model=list[FAQOut])
async def list_faqs(
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.KNOWLEDGE_READ)),
):
    return await svc.list_faqs(db)


@router.post("", response_model=FAQOut, status_code=status.HTTP_201_CREATED)
async def create_faq(
    body: FAQCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_perm(P.KNOWLEDGE_CREATE)),
):
    entry = await svc.create_faq(
        db,
        question=body.question,
        answer=body.answer,
        tags=body.tags,
        is_active=body.is_active,
        created_by_id=current_user.id,
    )
    await db.commit()
    await db.refresh(entry)
    return FAQOut.model_validate(entry)


@router.get("/{faq_id}", response_model=FAQOut)
async def get_faq(
    faq_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.KNOWLEDGE_READ)),
):
    entry = await svc.get_faq(db, faq_id)
    if not entry:
        raise NotFoundError("FAQ no encontrada")
    return FAQOut.model_validate(entry)


@router.patch("/{faq_id}", response_model=FAQOut)
async def update_faq(
    faq_id: uuid.UUID,
    body: FAQUpdate,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.KNOWLEDGE_UPDATE)),
):
    entry = await svc.get_faq(db, faq_id)
    if not entry:
        raise NotFoundError("FAQ no encontrada")
    entry = await svc.update_faq(db, entry, **body.model_dump(exclude_unset=True))
    await db.commit()
    await db.refresh(entry)
    return FAQOut.model_validate(entry)


@router.delete("/{faq_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_faq(
    faq_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.KNOWLEDGE_DELETE)),
):
    entry = await svc.get_faq(db, faq_id)
    if not entry:
        raise NotFoundError("FAQ no encontrada")
    await svc.delete_faq(db, entry)
    await db.commit()
