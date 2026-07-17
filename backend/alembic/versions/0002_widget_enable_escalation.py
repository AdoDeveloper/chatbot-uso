"""Agrega widget_config.enable_escalation

Master switch del escalamiento a humano en el widget. Default True: el
escalamiento estaba activo de facto (gobernado por reglas), así que el
comportamiento previo se preserva salvo que el admin lo apague.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-10
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    cols = [c["name"] for c in sa_inspect(bind).get_columns(table)]
    return column in cols


def upgrade() -> None:
    if not _has_column("widget_config", "enable_escalation"):
        op.add_column(
            "widget_config",
            sa.Column("enable_escalation", sa.Boolean, nullable=False, server_default=sa.true()),
        )


def downgrade() -> None:
    if _has_column("widget_config", "enable_escalation"):
        op.drop_column("widget_config", "enable_escalation")
