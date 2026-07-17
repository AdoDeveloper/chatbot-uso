"""Agrega widget_config.enable_tts

Activa o desactiva el botón de lectura en voz alta (TTS) junto a cada
respuesta del bot. Default True: preserva el comportamiento previo (el botón
ya se mostraba cuando el navegador soporta speechSynthesis).

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-11
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    cols = [c["name"] for c in sa_inspect(bind).get_columns(table)]
    return column in cols


def upgrade() -> None:
    if not _has_column("widget_config", "enable_tts"):
        op.add_column(
            "widget_config",
            sa.Column("enable_tts", sa.Boolean, nullable=False, server_default=sa.true()),
        )


def downgrade() -> None:
    if _has_column("widget_config", "enable_tts"):
        op.drop_column("widget_config", "enable_tts")
