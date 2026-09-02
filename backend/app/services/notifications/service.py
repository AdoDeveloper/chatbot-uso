from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import NotificationChannel, NotificationEvent, UserRole
from app.models.notification_log import NotificationLog
from app.models.notification_rule import NotificationRule
from app.models.user import User
from app.services.notifications import smtp
from app.services.notifications import templates as tpl
from app.services.notifications.audience import role_sees_event

log = structlog.get_logger()


async def _email_recipients(db: AsyncSession, target: str | None = None) -> list[str]:
    if target and target.strip():
        return [addr.strip() for addr in target.split(",") if addr.strip()]
    result = await db.execute(
        select(User.email).where(User.is_active.is_(True), User.role == UserRole.admin)
    )
    return [email for (email,) in result.all() if email]


async def _inapp_recipients(db: AsyncSession, event: NotificationEvent) -> list:
    roles_result = await db.execute(
        select(User.role).where(User.is_active.is_(True)).distinct()
    )
    active_roles = [r for (r,) in roles_result.all()]
    allowed_roles = [
        role for role in active_roles
        if await role_sees_event(db, role, event)
    ]
    if not allowed_roles:
        return []
    result = await db.execute(
        select(User.id).where(User.is_active.is_(True), User.role.in_(allowed_roles))
    )
    return [uid for (uid,) in result.all()]


async def send_notification(
    db: AsyncSession,
    *,
    event: NotificationEvent,
    payload: dict[str, Any],
) -> None:
    result = await db.execute(
        select(NotificationRule)
        .where(NotificationRule.event == event)
        .where(NotificationRule.enabled.is_(True))
    )
    rules = result.scalars().all()

    email_rule = next((r for r in rules if r.channel == NotificationChannel.email), None)
    inapp_rule = next((r for r in rules if r.channel == NotificationChannel.in_app), None)
    if not email_rule and not inapp_rule:
        log.info("notifications.dispatched", notif_event=event.value, skipped=True)
        return

    subject = _subject_for_event(event)
    body_html = _html_body(event, payload)
    body_text = _text_body(event, payload)

    # Comparten este id todas las filas de este disparo (agrupadas en el historial).
    trigger_id = uuid.uuid4()

    if email_rule:
        for to in await _email_recipients(db, email_rule.target):
            try:
                ok = await smtp.send_email(to=to, subject=subject, body_html=body_html, body_text=body_text)
                error_message = None if ok else "No se pudo enviar el correo (ver logs del servidor para el detalle)."
            except Exception as exc:
                ok = False
                error_message = str(exc)[:500]
                log.warning("notifications.email_send_failed", notif_event=event.value, target=to, error=str(exc))
            db.add(NotificationLog(
                trigger_id=trigger_id,
                event=event.value,
                channel=NotificationChannel.email.value,
                target=to,
                status="sent" if ok else "failed",
                error_message=error_message,
                payload_json=payload,
            ))

    inapp_recipients = 0
    if inapp_rule:
        for user_id in await _inapp_recipients(db, event):
            db.add(NotificationLog(
                trigger_id=trigger_id,
                event=event.value,
                channel=NotificationChannel.in_app.value,
                target="in_app",
                status="sent",
                error_message=None,
                payload_json=payload,
                user_id=user_id,
            ))
            inapp_recipients += 1

    await db.commit()
    log.info(
        "notifications.dispatched",
        notif_event=event.value,
        email=bool(email_rule),
        in_app=bool(inapp_rule),
        inapp_recipients=inapp_recipients,
    )


_EVENT_META = {
    NotificationEvent.doc_ready: {
        "subject": "Documento procesado correctamente",
        "severity": "success",
        "eyebrow": "Base de conocimiento",
        "intro": "Un documento ha finalizado su procesamiento y ya está disponible en la base de conocimiento.",
        "action": "Le recomendamos revisar el documento y aprobarlo para que el asistente pueda utilizarlo en sus respuestas.",
    },
    NotificationEvent.doc_error: {
        "subject": "Error al procesar un documento",
        "severity": "danger",
        "eyebrow": "Base de conocimiento",
        "intro": "Se produjo un error durante el procesamiento de un documento y no pudo incorporarse a la base de conocimiento.",
        "action": "Le recomendamos verificar el formato y el contenido del archivo, e intentar cargarlo nuevamente.",
    },
    NotificationEvent.escalation: {
        "subject": "Conversación escalada",
        "severity": "warning",
        "eyebrow": "Atención al usuario",
        "intro": "Una conversación ha sido escalada y requiere la atención del equipo.",
        "action": "Le recomendamos revisar el caso en la sección de conversaciones y dar seguimiento al usuario.",
    },
    NotificationEvent.provider_down: {
        "subject": "Proveedor de inteligencia artificial sin respuesta",
        "severity": "danger",
        "eyebrow": "Estado del sistema",
        "intro": "El proveedor de inteligencia artificial no está respondiendo. El asistente podría no generar respuestas mientras persista la incidencia.",
        "action": "Le recomendamos revisar el estado del proveedor y la configuración de sus credenciales.",
    },
    NotificationEvent.unanswered_digest: {
        "subject": "Resumen diario de preguntas sin respuesta",
        "severity": "info",
        "eyebrow": "Resumen diario",
        "intro": "Este es el resumen de las preguntas que el asistente no pudo responder en el último día.",
        "action": "Le recomendamos revisar las preguntas pendientes y considerar ampliar la base de conocimiento para cubrirlas.",
    },
    NotificationEvent.rate_limit_threshold: {
        "subject": "Límite de solicitudes cerca del máximo",
        "severity": "warning",
        "eyebrow": "Estado del sistema",
        "intro": "El número de solicitudes se aproxima al límite configurado. Si se alcanza, nuevas solicitudes podrían ser rechazadas temporalmente.",
        "action": "Le recomendamos revisar el tráfico reciente en la sección de cuotas y ajustar los límites si corresponde.",
    },
    NotificationEvent.service_down: {
        "subject": "Servicio degradado",
        "severity": "danger",
        "eyebrow": "Estado del sistema",
        "intro": "Uno de los servicios del sistema presenta una degradación que puede afectar el funcionamiento del asistente.",
        "action": "Le recomendamos revisar el estado de los servicios y los registros del servidor.",
    },
}

_FIELD_LABELS = {
    "open_questions": "Preguntas sin responder",
    "date": "Fecha",
    "document": "Documento",
    "source_id": "Identificador del documento",
    "source_name": "Documento",
    "chunks": "Fragmentos generados",
    "error": "Detalle del error",
    "conversation_id": "Identificador de conversación",
    "question": "Pregunta",
    "reason": "Motivo",
    "service": "Servicio",
    "providers": "Proveedores intentados",
    "since": "Sin responder desde",
    "current_requests_last_hour": "Solicitudes en la última hora",
    "limit_per_hour": "Límite por hora",
    "percent": "Porcentaje del límite",
    "contact_email": "Contacto por correo electrónico",
    "contact_whatsapp": "Contacto por WhatsApp",
}


def _meta(event: NotificationEvent) -> dict[str, str]:
    return _EVENT_META.get(event, {
        "subject": f"Notificación: {event.value}",
        "severity": "neutral",
        "eyebrow": "Notificación",
        "intro": "",
        "action": "",
    })


def _subject_for_event(event: NotificationEvent) -> str:
    return _meta(event)["subject"]


def _labeled_rows(payload: dict[str, Any]) -> dict[str, Any]:
    return {_FIELD_LABELS.get(k, k.replace("_", " ").capitalize()): v for k, v in payload.items()}


# Misma zona horaria que frontend/src/lib/datetime.ts::PROJECT_TIMEZONE.
_PROJECT_TZ = ZoneInfo("America/El_Salvador")


def _humanize_since(iso_str: str) -> tuple[str, str]:
    """Convierte un ISO 8601 UTC a (fecha legible en hora local, hace cuánto)."""
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return iso_str, ""

    local = dt.astimezone(_PROJECT_TZ)
    months = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
    readable = f"{local.day} de {months[local.month - 1]} de {local.year}, {local.strftime('%I:%M %p').lstrip('0')}"

    elapsed = datetime.now(timezone.utc) - dt
    total_seconds = int(elapsed.total_seconds())
    if total_seconds < 60:
        ago = "hace un momento"
    elif total_seconds < 3600:
        mins = total_seconds // 60
        ago = f"hace {mins} minuto{'s' if mins != 1 else ''}"
    elif total_seconds < 86400:
        hours = total_seconds // 3600
        ago = f"hace {hours} hora{'s' if hours != 1 else ''}"
    else:
        days = total_seconds // 86400
        ago = f"hace {days} día{'s' if days != 1 else ''}"

    return readable, ago


def _html_body(event: NotificationEvent, payload: dict[str, Any]) -> str:
    m = _meta(event)

    if event is NotificationEvent.unanswered_digest and "total_open" in payload:
        return _daily_digest_body(m, payload)

    if event is NotificationEvent.provider_down and "providers" in payload:
        return _provider_down_body(m, payload)

    content = ""
    if m["intro"]:
        content += tpl.paragraph(m["intro"])

    if payload:
        content += tpl.detail_table(_labeled_rows(payload), heading_text="Detalle")

    if m["action"]:
        content += tpl.paragraph(m["action"])

    return tpl.render_email(title=m["subject"], content=content, preheader=m["intro"])


def _daily_digest_body(m: dict[str, str], p: dict[str, Any]) -> str:
    """Cuerpo enriquecido del resumen diario.

    El texto se adapta según haya o no preguntas pendientes: cuando no quedan
    pendientes, el mensaje y la recomendación cambian para no sonar incoherentes.
    """
    total_open = int(p.get("total_open", 0) or 0)

    if total_open == 0:
        intro = "Durante el último día el asistente respondió todas las consultas y no quedaron preguntas pendientes de atención."
    else:
        intro = m["intro"]
    content = tpl.paragraph(intro)

    # Cifras principales: nuevas, acumuladas, resueltas, escaladas.
    content += tpl.stat_grid([
        (p.get("new_open", 0), "Nuevas sin responder"),
        (p.get("total_open", 0), "Acumuladas pendientes"),
        (p.get("resolved_today", 0), "Resueltas hoy"),
        (p.get("escalated_today", 0), "Conversaciones escaladas"),
    ])

    # Temas y preguntas solo cuando hay pendientes.
    topics = p.get("top_topics") or []
    if topics:
        content += tpl.heading("Temas más frecuentes")
        content += tpl.topic_list([(str(t), int(n)) for t, n in topics])

    recent = p.get("recent_questions") or []
    if recent:
        content += tpl.heading("Preguntas recientes sin responder")
        content += tpl.quote_list([str(q) for q in recent])

    # Recomendación coherente con el estado.
    if total_open == 0:
        content += tpl.paragraph("No se requiere ninguna acción por el momento.")
    elif m["action"]:
        content += tpl.paragraph(m["action"])

    return tpl.render_email(title=m["subject"], content=content, preheader=intro)


def _provider_down_body(m: dict[str, str], p: dict[str, Any]) -> str:
    """Cuerpo enriquecido de la alerta de proveedor caído: tabla propia por
    proveedor, tabla de fecha/tiempo transcurrido, y tabla de error."""
    content = tpl.paragraph(m["intro"])

    providers = [s.strip() for s in str(p.get("providers", "")).split(",") if s.strip()]
    if providers:
        content += tpl.heading(
            "Proveedor intentado" if len(providers) == 1 else "Proveedores intentados"
        )
        for provider_name in providers:
            content += tpl.detail_table(
                {"Proveedor": provider_name, "Estado": "Sin respuesta"}
            )

    since = p.get("since")
    if since:
        readable, ago = _humanize_since(str(since))
        rows: dict[str, object] = {"Sin responder desde": readable}
        if ago:
            rows["Tiempo transcurrido"] = ago
        content += tpl.heading("Duración de la incidencia")
        content += tpl.detail_table(rows)

    error = p.get("error")
    if error and error != "(sin detalle)":
        content += tpl.heading("Detalle del error")
        content += tpl.detail_table({"Mensaje": str(error)})

    if m["action"]:
        content += tpl.paragraph(m["action"])

    return tpl.render_email(title=m["subject"], content=content, preheader=m["intro"])


def _text_body(event: NotificationEvent, payload: dict[str, Any]) -> str:
    m = _meta(event)
    lines = [m["subject"], ""]
    if m["intro"]:
        lines += [m["intro"], ""]

    if event is NotificationEvent.provider_down and "since" in payload:
        readable, ago = _humanize_since(str(payload["since"]))
        payload = {**payload, "since": f"{readable} ({ago})" if ago else readable}

    for k, v in _labeled_rows(payload).items():
        lines.append(f"{k}: {v}")
    if m["action"]:
        lines += ["", f"Acción recomendada: {m['action']}"]
    lines += ["", f"{tpl.BRAND_NAME}."]
    return "\n".join(lines)
