"""Agrega widget_config.enable_accessibility

Master switch del menú de accesibilidad (tamaño de texto + alto contraste +
TTS) en el kebab del widget. Independiente de enable_tts: si está en False,
la opción «Accesibilidad» no aparece en absoluto. Default True: preserva el
comportamiento previo (el menú ya se mostraba siempre).

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-11
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    cols = [c["name"] for c in sa_inspect(bind).get_columns(table)]
    return column in cols


def upgrade() -> None:
    if not _has_column("widget_config", "enable_accessibility"):
        op.add_column(
            "widget_config",
            sa.Column("enable_accessibility", sa.Boolean, nullable=False, server_default=sa.true()),
        )


def downgrade() -> None:
    if _has_column("widget_config", "enable_accessibility"):
        op.drop_column("widget_config", "enable_accessibility")
