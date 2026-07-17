"""Initial schema — full database creation from scratch

Migración única consolidada para MySQL 8.0.
Tipos utilizados:
  - UUID  → sa.Uuid(native_uuid=False)  → CHAR(36)
  - JSONB → sa.JSON                     → JSON (nativo MySQL 8.0)
  - ARRAY → sa.Text                     → TEXT (JSONList serializa como JSON string)
  - ENUM  → sa.Enum(*values)            → ENUM nativo MySQL

Incluye: esquema completo + users.tokens_valid_after (JWT mass-revocation)
+ columnas de widget_config: enable_escalation, enable_tts,
enable_accessibility (unificadas desde las migraciones 0002-0004, que
se fusionaron aquí en desarrollo con BD regenerable).

Revision ID: 0001
Revises: —
Create Date: 2026-06-12
Updated 2026-07-03: consolidada — ya no crea escalation_channels (nunca se
conectó al despacho real de escalamientos, siempre usó SMTP directo).
Updated 2026-07-14: unificadas las migraciones 0002-0004 en esta
única (widget_config.enable_escalation / enable_tts / enable_accessibility).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Valores de cada enum (mismos que los modelos Python)
_E = {
    "conversationstatus": ("active", "escalated", "resolved"),
    "messagerole":        ("user", "assistant"),
    "messagefeedback":    ("positive", "negative"),
    "sourcetype":         ("pdf", "docx", "xlsx", "csv", "txt", "faq"),
    "sourcestatus":       ("pending", "processing", "ready", "error"),
    "reviewstatus":       ("procesando", "pendiente_revision", "aprobada", "rechazada"),
    "unansweredstatus":   ("open", "in_progress", "resolved"),
    "notificationevent":  (
        "doc_ready", "doc_error", "escalation", "provider_down",
        "unanswered_daily", "rate_limit_threshold", "service_down",
    ),
    "notificationchannel":   ("email", "in_app"),
    "escalationtrigger":     (
        "no_answer", "user_request", "negative_feedback",
        "keyword_detected", "confidence_below", "loop_detected",
    ),
    "escalationeventtype":   (
        "escalated", "assigned", "unassigned", "resolved", "abandoned", "csat_recorded",
    ),
    "permissionaction": ("create", "read", "update", "delete", "manage"),
}


def _e(name: str) -> sa.Enum:
    """Enum inline para columna — sin nombre de tipo (MySQL lo ignora)."""
    return sa.Enum(*_E[name])


def _ct(name: str, *cols, **kw) -> None:
    """CREATE TABLE seguro para MySQL: salta si la tabla ya existe.

    MySQL DDL es no-transaccional; una migración fallida puede dejar
    tablas parcialmente creadas. Este helper evita OperationalError 1050
    al reintentar sin borrar el volumen.
    """
    if sa_inspect(op.get_bind()).has_table(name):
        return
    op.create_table(name, *cols, **kw)


def _ci(index_name: str, table_name: str, columns: list, *, unique: bool = False) -> None:
    """CREATE INDEX seguro para MySQL: salta si el índice ya existe."""
    try:
        existing = {i["name"] for i in sa_inspect(op.get_bind()).get_indexes(table_name)}
    except Exception:
        existing = set()
    if index_name not in existing:
        op.create_index(index_name, table_name, columns, unique=unique)


def upgrade() -> None:
    # MySQL 8.0: no existen tipos ENUM nombrados a nivel servidor;
    # el ENUM se define inline en cada columna — no hay paso previo de creación.

    # roles — no dependencies
    _ct(
        "roles",
        sa.Column("id",           sa.Uuid(native_uuid=False), primary_key=True),
        sa.Column("name",         sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("description",  sa.Text,        nullable=True),
        sa.Column("is_system",    sa.Boolean,     nullable=False, server_default=sa.false()),
        sa.Column("created_at",   sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    _ci("ix_roles_name", "roles", ["name"], unique=True)

    # modules — no dependencies
    _ct(
        "modules",
        sa.Column("id",           sa.Uuid(native_uuid=False), primary_key=True),
        sa.Column("name",         sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("description",  sa.Text,        nullable=True),
        sa.Column("is_active",    sa.Boolean,     nullable=False, server_default=sa.true()),
        sa.Column("created_at",   sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    _ci("ix_modules_name", "modules", ["name"], unique=True)

    # users
    _ct(
        "users",
        sa.Column("id",                   sa.Uuid(native_uuid=False), primary_key=True),
        sa.Column("email",                sa.String(255), nullable=False),
        sa.Column("full_name",            sa.String(255), nullable=False),
        sa.Column("hashed_password",      sa.String(255), nullable=False),
        sa.Column("role",                 sa.String(100), nullable=False),
        sa.Column("is_active",            sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("must_change_password", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("onboarding_dismissed", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("last_login_at",        sa.DateTime(timezone=True), nullable=True),
        sa.Column("tokens_valid_after",    sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at",     sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at",     sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    _ci("ix_users_email", "users", ["email"], unique=True)

    # permissions — depends on modules
    _ct(
        "permissions",
        sa.Column("id",          sa.Uuid(native_uuid=False), primary_key=True),
        sa.Column("module_id",   sa.Uuid(native_uuid=False), sa.ForeignKey("modules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action",      _e("permissionaction"), nullable=False),
        sa.Column("name",        sa.String(150), nullable=False),
        sa.Column("description", sa.Text,        nullable=True),
        sa.Column("created_at",  sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("module_id", "action", name="uq_permission_module_action"),
    )
    _ci("ix_permissions_name", "permissions", ["name"], unique=True)

    # role_permissions — depends on roles, permissions
    _ct(
        "role_permissions",
        sa.Column("id",            sa.Uuid(native_uuid=False), primary_key=True),
        sa.Column("role",          sa.String(100), sa.ForeignKey("roles.name", onupdate="CASCADE", ondelete="CASCADE"), nullable=False),
        sa.Column("permission_id", sa.Uuid(native_uuid=False), sa.ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("granted_at",    sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("role", "permission_id", name="uq_role_permission"),
    )
    _ci("ix_role_permissions_role", "role_permissions", ["role"])

    # invitations — depends on roles, users
    _ct(
        "invitations",
        sa.Column("id",             sa.Uuid(native_uuid=False), primary_key=True),
        sa.Column("email",          sa.String(255), nullable=False),
        sa.Column("role",           sa.String(100), sa.ForeignKey("roles.name", onupdate="CASCADE", ondelete="RESTRICT"), nullable=False),
        sa.Column("token",          sa.String(64),  nullable=False),
        sa.Column("created_by_id",  sa.Uuid(native_uuid=False), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("expires_at",     sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at",    sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active",      sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at",     sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    _ci("ix_invitations_email", "invitations", ["email"])
    _ci("ix_invitations_token", "invitations", ["token"], unique=True)

    # global_settings — depends on users
    _ct(
        "global_settings",
        sa.Column("key",            sa.String(100), primary_key=True),
        sa.Column("value",          sa.JSON, nullable=False),
        sa.Column("updated_at",     sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_by_id",  sa.Uuid(native_uuid=False), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )

    # widget_config — no FK dependencies
    # domain_allowlist / suggestions usan sa.Text (JSONList → JSON string en TEXT)
    _ct(
        "widget_config",
        sa.Column("id",                    sa.Uuid(native_uuid=False), primary_key=True),
        sa.Column("api_key",               sa.String(40),  nullable=False, server_default=sa.text("('')")),
        sa.Column("chatbot_name",          sa.String(128), nullable=False, server_default="Asistente"),
        sa.Column("welcome_message",       sa.Text,        nullable=False, server_default=sa.text("('¡Hola! ¿En qué puedo ayudarte?')")),
        sa.Column("primary_color",         sa.String(16),  nullable=False, server_default="#1C386D"),
        sa.Column("position",              sa.String(16),  nullable=False, server_default="bottom-right"),
        sa.Column("logo_url",              sa.Text,        nullable=True),
        sa.Column("domain_allowlist",      sa.Text,        nullable=False, server_default=sa.text("('[]')")),
        sa.Column("show_sources",          sa.Boolean,     nullable=False, server_default=sa.true()),
        sa.Column("enable_copy_action",    sa.Boolean,     nullable=False, server_default=sa.true()),
        sa.Column("enable_feedback_icons", sa.Boolean,     nullable=False, server_default=sa.true()),
        sa.Column("show_bot_icon",         sa.Boolean,     nullable=False, server_default=sa.true()),
        sa.Column("suggestions",           sa.Text,        nullable=False, server_default=sa.text("('[]')")),
        sa.Column("proactive_message",     sa.Text,        nullable=False, server_default=sa.text("('')")),
        sa.Column("launcher_label",        sa.Text,        nullable=False, server_default=sa.text("('')")),
        sa.Column("max_chats_per_session", sa.Integer,     nullable=True),
        sa.Column("max_chats_per_day",     sa.Integer,     nullable=True),
        sa.Column("show_end_chat_button",  sa.Boolean,     nullable=False, server_default=sa.true()),
        sa.Column("show_new_chat_button",  sa.Boolean,     nullable=False, server_default=sa.true()),
        sa.Column("enable_csat",           sa.Boolean,     nullable=False, server_default=sa.false()),
        sa.Column("csat_question",         sa.Text,        nullable=False, server_default=sa.text("('¿Cómo calificarías esta conversación?')")),
        sa.Column("enable_escalation",     sa.Boolean,     nullable=False, server_default=sa.true()),
        sa.Column("enable_tts",            sa.Boolean,     nullable=False, server_default=sa.true()),
        sa.Column("enable_accessibility",   sa.Boolean,     nullable=False, server_default=sa.true()),
        sa.Column("updated_at",            sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    _ci("ix_widget_config_api_key", "widget_config", ["api_key"], unique=True)

    # llm_providers — no FK dependencies
    _ct(
        "llm_providers",
        sa.Column("id",                    sa.Uuid(native_uuid=False), primary_key=True),
        sa.Column("name",                  sa.String(120), nullable=False),
        sa.Column("provider_type",         sa.String(50),  nullable=False),
        sa.Column("model_name",            sa.String(120), nullable=False),
        sa.Column("api_key_encrypted",     sa.Text,        nullable=True),
        sa.Column("api_base",              sa.String(512), nullable=True),
        sa.Column("dashboard_url",         sa.String(512), nullable=True),
        sa.Column("is_active",             sa.Boolean,     nullable=False, server_default=sa.true()),
        sa.Column("priority",              sa.Integer,     nullable=True),
        sa.Column("created_at",            sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at",            sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_test_at",          sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_ok",          sa.Boolean,     nullable=True),
        sa.Column("last_test_latency_ms",  sa.Integer,     nullable=True),
        sa.Column("last_test_error",       sa.Text,        nullable=True),
    )

    # sources — depends on users
    _ct(
        "sources",
        sa.Column("id",               sa.Uuid(native_uuid=False), primary_key=True),
        sa.Column("name",             sa.String(255), nullable=False),
        sa.Column("type",             _e("sourcetype"),   nullable=False),
        sa.Column("status",           _e("sourcestatus"), nullable=False, server_default="pending"),
        sa.Column("review_status",    _e("reviewstatus"), nullable=False, server_default="procesando"),
        sa.Column("reviewed_by_id",   sa.Uuid(native_uuid=False), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewed_at",      sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text,        nullable=True),
        sa.Column("file_path",        sa.String(512), nullable=True),
        sa.Column("file_size",        sa.Integer,     nullable=True),
        sa.Column("chunk_count",      sa.Integer,     nullable=False, server_default="0"),
        sa.Column("error_message",    sa.Text,        nullable=True),
        sa.Column("error_code",       sa.String(64),  nullable=True),
        sa.Column("error_hint",       sa.Text,        nullable=True),
        sa.Column("progress_stage",   sa.String(50),  nullable=True),
        sa.Column("content_hash",     sa.String(64),  nullable=True),
        sa.Column("meta",             sa.JSON,        nullable=False, server_default=sa.text("('{}')") ),
        sa.Column("created_by_id",    sa.Uuid(native_uuid=False), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at",       sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at",       sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at",       sa.DateTime(timezone=True), nullable=True),
    )
    _ci("ix_sources_review_status", "sources", ["review_status"])
    _ci("ix_sources_content_hash",  "sources", ["content_hash"])

    # faq_entries — depends on sources, users
    # tags usa sa.Text (JSONList → JSON string)
    _ct(
        "faq_entries",
        sa.Column("id",             sa.Uuid(native_uuid=False), primary_key=True),
        sa.Column("question",       sa.Text,    nullable=False),
        sa.Column("answer",         sa.Text,    nullable=False),
        sa.Column("tags",           sa.Text,    nullable=False, server_default=sa.text("('[]')")),
        sa.Column("is_active",      sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("source_id",      sa.Uuid(native_uuid=False), sa.ForeignKey("sources.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by_id",  sa.Uuid(native_uuid=False), sa.ForeignKey("users.id",   ondelete="SET NULL"), nullable=True),
        sa.Column("created_at",     sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at",     sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at",     sa.DateTime(timezone=True), nullable=True),
    )
    _ci("ix_faq_entries_is_active", "faq_entries", ["is_active"])

    # chunk_edits — depends on sources, users
    _ct(
        "chunk_edits",
        sa.Column("id",               sa.Uuid(native_uuid=False), primary_key=True),
        sa.Column("chunk_point_id",   sa.String(64), nullable=False),
        sa.Column("source_id",        sa.Uuid(native_uuid=False), sa.ForeignKey("sources.id",  ondelete="CASCADE"),  nullable=False),
        sa.Column("previous_content", sa.Text,       nullable=False),
        sa.Column("new_content",      sa.Text,       nullable=False),
        sa.Column("edited_by_id",     sa.Uuid(native_uuid=False), sa.ForeignKey("users.id",    ondelete="SET NULL"), nullable=True),
        sa.Column("reason",           sa.Text,       nullable=True),
        sa.Column("edited_at",        sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    _ci("ix_chunk_edits_chunk_point_id", "chunk_edits", ["chunk_point_id"])
    _ci("ix_chunk_edits_source_id",      "chunk_edits", ["source_id"])
    _ci("ix_chunk_edits_edited_at",      "chunk_edits", ["edited_at"])

    # chat_conversations — depends on users
    # tags usa sa.Text (JSONList)
    _ct(
        "chat_conversations",
        sa.Column("id",                          sa.Uuid(native_uuid=False), primary_key=True),
        sa.Column("session_id",                  sa.String(128), nullable=False),
        sa.Column("user_id",                     sa.Uuid(native_uuid=False), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status",                      _e("conversationstatus"), nullable=False, server_default="active"),
        sa.Column("device",                      sa.String(64), nullable=True),
        sa.Column("browser",                     sa.String(64), nullable=True),
        sa.Column("origin_url",                  sa.Text,       nullable=True),
        sa.Column("created_at",                  sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at",                  sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_message_at",             sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("escalated_at",                sa.DateTime(timezone=True), nullable=True),
        sa.Column("assigned_to_user_id",         sa.Uuid(native_uuid=False), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("assigned_at",                 sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at",                 sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_user_id",         sa.Uuid(native_uuid=False), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("csat_score",                  sa.Integer,    nullable=True),
        sa.Column("csat_comment",                sa.String(500), nullable=True),
        sa.Column("escalation_pending",          sa.Boolean,    nullable=False, server_default=sa.false()),
        sa.Column("escalation_trigger_reason",   sa.Text,       nullable=True),
        sa.Column("tags",                        sa.Text,       nullable=False, server_default=sa.text("('[]')")),
    )
    _ci("ix_chat_conversations_session_id",           "chat_conversations", ["session_id"])
    _ci("ix_chat_conversations_user_id",              "chat_conversations", ["user_id"])
    _ci("ix_chat_conversations_assigned_to_user_id",  "chat_conversations", ["assigned_to_user_id"])

    # chat_messages — depends on chat_conversations
    # sources_json usa sa.JSON (JSONList — lista de dicts con source_name, score, etc.)
    _ct(
        "chat_messages",
        sa.Column("id",              sa.Uuid(native_uuid=False), primary_key=True),
        sa.Column("conversation_id", sa.Uuid(native_uuid=False), sa.ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role",            _e("messagerole"),    nullable=False),
        sa.Column("content",         sa.Text,              nullable=False),
        sa.Column("sources_json",    sa.JSON,              nullable=False, server_default=sa.text("('[]')")),
        sa.Column("latency_ms",      sa.Integer,           nullable=True),
        sa.Column("rag_route",       sa.String(32),        nullable=True),
        sa.Column("feedback",        _e("messagefeedback"), nullable=True),
        sa.Column("annotation",      sa.String(32),        nullable=True),
        sa.Column("annotation_note", sa.Text,              nullable=True),
        sa.Column("created_at",      sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    _ci("ix_chat_messages_conversation_id",       "chat_messages", ["conversation_id"])
    _ci("ix_chat_messages_conversation_created",  "chat_messages", ["conversation_id", "created_at"])

    # escalation_events — depends on chat_conversations, users
    _ct(
        "escalation_events",
        sa.Column("id",              sa.Uuid(native_uuid=False), primary_key=True),
        sa.Column("conversation_id", sa.Uuid(native_uuid=False), sa.ForeignKey("chat_conversations.id", ondelete="CASCADE"),  nullable=False),
        sa.Column("event_type",      _e("escalationeventtype"), nullable=False),
        sa.Column("actor_user_id",   sa.Uuid(native_uuid=False), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("target_user_id",  sa.Uuid(native_uuid=False), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("note",            sa.Text, nullable=True),
        sa.Column("meta_json",       sa.JSON, nullable=False, server_default=sa.text("('{}')") ),
        sa.Column("trigger_type",    sa.String(64), nullable=True),
        sa.Column("created_at",      sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    _ci("ix_escalation_events_conversation_id", "escalation_events", ["conversation_id"])

    # unanswered_questions — depends on chat_conversations, users
    _ct(
        "unanswered_questions",
        sa.Column("id",              sa.Uuid(native_uuid=False), primary_key=True),
        sa.Column("conversation_id", sa.Uuid(native_uuid=False), sa.ForeignKey("chat_conversations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("question",        sa.Text,       nullable=False),
        sa.Column("detected_topic",  sa.String(128), nullable=True),
        sa.Column("status",          _e("unansweredstatus"), nullable=False, server_default="open"),
        sa.Column("resolved_by_id",  sa.Uuid(native_uuid=False), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resolved_at",     sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at",      sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    _ci("ix_unanswered_questions_conversation_id", "unanswered_questions", ["conversation_id"])
    _ci("ix_unanswered_questions_detected_topic",  "unanswered_questions", ["detected_topic"])
    _ci("ix_unanswered_questions_status",          "unanswered_questions", ["status"])

    # notification_rules — no FK dependencies
    _ct(
        "notification_rules",
        sa.Column("id",          sa.Uuid(native_uuid=False), primary_key=True),
        sa.Column("event",       _e("notificationevent"),   nullable=False),
        sa.Column("channel",     _e("notificationchannel"), nullable=False),
        sa.Column("enabled",     sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("target",      sa.Text,    nullable=True),
        sa.Column("config_json", sa.JSON,    nullable=False, server_default=sa.text("('{}')") ),
        sa.Column("updated_at",  sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("event", "channel", name="uq_notification_rules_event_channel"),
    )
    _ci("ix_notification_rules_event", "notification_rules", ["event"])

    # notification_logs — no FK dependencies
    _ct(
        "notification_logs",
        sa.Column("id",            sa.Uuid(native_uuid=False), primary_key=True),
        sa.Column("event",         sa.String(50),  nullable=False),
        sa.Column("channel",       sa.String(20),  nullable=False),
        sa.Column("target",        sa.String(255), nullable=False),
        sa.Column("status",        sa.String(20),  nullable=False),
        sa.Column("error_message", sa.Text,        nullable=True),
        sa.Column("payload_json",  sa.JSON,        nullable=False, server_default=sa.text("('{}')") ),
        sa.Column("created_at",    sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("read_at",       sa.DateTime(timezone=True), nullable=True),
    )
    _ci("ix_notification_logs_event",      "notification_logs", ["event"])
    _ci("ix_notification_logs_created_at", "notification_logs", ["created_at"])

    # escalation_rules — no FK dependencies
    _ct(
        "escalation_rules",
        sa.Column("id",             sa.Uuid(native_uuid=False), primary_key=True),
        sa.Column("name",           sa.String(128), nullable=False, server_default=sa.text("('')")),
        sa.Column("description",    sa.Text,        nullable=False, server_default=sa.text("('')")),
        sa.Column("trigger_type",   _e("escalationtrigger"), nullable=False),
        sa.Column("trigger_config", sa.JSON,        nullable=False, server_default=sa.text("('{}')") ),
        sa.Column("enabled",        sa.Boolean,     nullable=False, server_default=sa.true()),
        sa.Column("created_at",     sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at",     sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # audit_logs — depends on users
    _ct(
        "audit_logs",
        sa.Column("id",            sa.Uuid(native_uuid=False), primary_key=True),
        sa.Column("actor_id",      sa.Uuid(native_uuid=False), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action",        sa.String(128), nullable=False),
        sa.Column("resource_type", sa.String(64),  nullable=False),
        sa.Column("resource_id",   sa.String(128), nullable=True),
        sa.Column("meta_json",     sa.JSON,        nullable=False, server_default=sa.text("('{}')") ),
        sa.Column("ip",            sa.String(64),  nullable=True),
        sa.Column("user_agent",    sa.Text,        nullable=True),
        sa.Column("created_at",    sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    _ci("ix_audit_logs_actor_id",      "audit_logs", ["actor_id"])
    _ci("ix_audit_logs_action",        "audit_logs", ["action"])
    _ci("ix_audit_logs_resource_type", "audit_logs", ["resource_type"])
    _ci("ix_audit_logs_created_at",    "audit_logs", ["created_at"])
    op.create_index("ix_audit_logs_actor_created", "audit_logs", ["actor_id", "created_at"])

    # rate_limit_events — no FK dependencies
    _ct(
        "rate_limit_events",
        sa.Column("id",                    sa.Uuid(native_uuid=False), primary_key=True),
        sa.Column("dimension",             sa.String(64),  nullable=False),
        sa.Column("identifier",            sa.String(128), nullable=False),
        sa.Column("identifier_type",       sa.String(16),  nullable=False, server_default=sa.text("('ip')")),
        sa.Column("limit_value",           sa.Integer,     nullable=False, server_default=sa.text("(0)")),
        sa.Column("retry_after_seconds",   sa.Integer,     nullable=True),
        sa.Column("created_at",            sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    _ci("ix_rate_limit_events_dimension",  "rate_limit_events", ["dimension"])
    _ci("ix_rate_limit_events_identifier", "rate_limit_events", ["identifier"])
    _ci("ix_rate_limit_events_created_at", "rate_limit_events", ["created_at"])

    # health_snapshots — no FK dependencies
    _ct(
        "health_snapshots",
        sa.Column("id",           sa.Uuid(native_uuid=False), primary_key=True),
        sa.Column("service_name", sa.String(64), nullable=False),
        sa.Column("is_ok",        sa.Boolean,   nullable=False),
        sa.Column("latency_ms",   sa.Integer,   nullable=True),
        sa.Column("error",        sa.Text,      nullable=True),
        sa.Column("recorded_at",  sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("cpu_percent",  sa.Float,     nullable=True),
        sa.Column("mem_percent",  sa.Float,     nullable=True),
        sa.Column("disk_percent", sa.Float,     nullable=True),
    )
    _ci("ix_health_snapshots_service_name", "health_snapshots", ["service_name"])
    _ci("ix_health_snapshots_recorded_at",  "health_snapshots", ["recorded_at"])

    # config_versions — depends on users, self-referential FK
    _ct(
        "config_versions",
        sa.Column("id",                      sa.Uuid(native_uuid=False), primary_key=True),
        sa.Column("version_number",          sa.Integer, nullable=False, server_default=sa.text("(0)")),
        sa.Column("description",             sa.String(500), nullable=False, server_default=""),
        sa.Column("config_snapshot",         sa.JSON,    nullable=False, server_default=sa.text("('{}')")),
        sa.Column("is_active",               sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("snapshot_schema_version", sa.Integer, nullable=False, server_default="2"),
        sa.Column("change_summary",          sa.String(1000), nullable=True),
        sa.Column("trigger_source",          sa.String(50),   nullable=True),
        sa.Column("parent_version_id",       sa.Uuid(native_uuid=False), sa.ForeignKey("config_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by_id",           sa.Uuid(native_uuid=False), sa.ForeignKey("users.id",            ondelete="SET NULL"), nullable=True),
        sa.Column("created_at",              sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    _ci("ix_config_versions_parent_version_id", "config_versions", ["parent_version_id"])


def downgrade() -> None:
    op.drop_table("config_versions")
    op.drop_table("health_snapshots")
    op.drop_table("rate_limit_events")
    op.drop_index("ix_audit_logs_actor_created", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("escalation_rules")
    op.drop_table("notification_logs")
    op.drop_table("notification_rules")
    op.drop_table("unanswered_questions")
    op.drop_table("escalation_events")
    op.drop_table("chat_messages")
    op.drop_table("chat_conversations")
    op.drop_table("chunk_edits")
    op.drop_table("faq_entries")
    op.drop_table("sources")
    op.drop_table("llm_providers")
    op.drop_table("widget_config")
    op.drop_table("global_settings")
    op.drop_table("invitations")
    op.drop_table("role_permissions")
    op.drop_table("permissions")
    op.drop_table("users")
    op.drop_table("modules")
    op.drop_table("roles")
    # MySQL: no hay tipos ENUM nombrados a nivel servidor — nada que limpiar aquí.
