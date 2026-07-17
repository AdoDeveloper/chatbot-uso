import enum


class UserRole(str, enum.Enum):
    admin  = "admin"    # Administrador total
    editor = "editor"   # Solo fuentes/documentos
    viewer = "viewer"   # Solo lectura


class SourceType(str, enum.Enum):
    pdf = "pdf"
    docx = "docx"
    xlsx = "xlsx"
    csv = "csv"
    txt = "txt"
    faq = "faq"


class SourceStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    ready = "ready"
    error = "error"


class ConversationStatus(str, enum.Enum):
    active = "active"        # conversación normal con el bot
    escalated = "escalated"  # pendiente de atención humana
    resolved = "resolved"    # cerrada / atendida


class EscalationEventType(str, enum.Enum):
    """Lifecycle event in an escalated conversation."""
    escalated = "escalated"          # conversation entered escalated state
    assigned = "assigned"            # admin took ownership
    unassigned = "unassigned"        # admin released ownership
    resolved = "resolved"            # admin marked as resolved
    abandoned = "abandoned"          # closed without resolution
    csat_recorded = "csat_recorded"  # post-attention satisfaction score


class MessageRole(str, enum.Enum):
    user = "user"
    assistant = "assistant"


class MessageFeedback(str, enum.Enum):
    positive = "positive"
    negative = "negative"


class UnansweredStatus(str, enum.Enum):
    open = "open"
    in_progress = "in_progress"
    resolved = "resolved"


class NotificationEvent(str, enum.Enum):
    doc_ready = "doc_ready"
    doc_error = "doc_error"
    escalation = "escalation"
    provider_down = "provider_down"
    unanswered_daily = "unanswered_daily"
    rate_limit_threshold = "rate_limit_threshold"
    service_down = "service_down"


class NotificationChannel(str, enum.Enum):
    email = "email"
    in_app = "in_app"


class EscalationTrigger(str, enum.Enum):
    no_answer = "no_answer"
    user_request = "user_request"
    negative_feedback = "negative_feedback"
    keyword_detected = "keyword_detected"
    confidence_below = "confidence_below"
    loop_detected = "loop_detected"


class PermissionAction(str, enum.Enum):
    create = "create"
    read = "read"
    update = "update"
    delete = "delete"
    manage = "manage"


class ReviewStatus(str, enum.Enum):
    """
    Approval lifecycle for a Source (independent from ingestion `status`).

    - procesando:         ingestion still running (chunks not yet generated)
    - pendiente_revision: chunks generated, awaiting admin review
    - aprobada:           admin reviewed and accepted; required before promote→prod
    - rechazada:          admin rejected; source is archived (not deleted)
    """
    procesando = "procesando"
    pendiente_revision = "pendiente_revision"
    aprobada = "aprobada"
    rechazada = "rechazada"
