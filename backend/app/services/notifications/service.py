from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import NotificationChannel, NotificationEvent, UserRole
from app.models.notification_log import NotificationLog
from app.models.notification_rule import NotificationRule
from app.models.user import User
from app.services.notifications import smtp
from app.services.notifications import templates as tpl

log = structlog.get_logger()


async def _email_recipients(db: AsyncSession) -> list[str]:
    result = await db.execute(
        select(User.email).where(User.is_active.is_(True), User.role == UserRole.admin)
    )
    return [email for (email,) in result.all()]


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

    if email_rule:
        for to in await _email_recipients(db):
            ok = await smtp.send_email(to=to, subject=subject, body_html=body_html, body_text=body_text)
            db.add(NotificationLog(
                event=event.value,
                channel=NotificationChannel.email.value,
                target=to,
                status="sent" if ok else "failed",
                error_message=None if ok else "No se pudo enviar el correo (ver logs del servidor para el detalle).",
                payload_json=payload,
            ))

    if inapp_rule:
        db.add(NotificationLog(
            event=event.value,
            channel=NotificationChannel.in_app.value,
            target="in_app",
            status="sent",
            error_message=None,
            payload_json=payload,
        ))

    await db.commit()
    log.info(
        "notifications.dispatched",
        notif_event=event.value,
        email=bool(email_rule),
        in_app=bool(inapp_rule),
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
    NotificationEvent.unanswered_daily: {
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

# Etiquetas legibles para las claves técnicas del payload.
_FIELD_LABELS = {
    "open_questions": "Preguntas sin responder",
    "date": "Fecha",
    "document": "Documento",
    "source_name": "Documento",
    "error": "Detalle del error",
    "conversation_id": "Identificador de conversación",
    "question": "Pregunta",
    "reason": "Motivo",
    "provider": "Proveedor",
    "service": "Servicio",
    "count": "Cantidad",
    "current": "Valor actual",
    "limit": "Límite",
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


def _html_body(event: NotificationEvent, payload: dict[str, Any]) -> str:
    m = _meta(event)

    if event is NotificationEvent.unanswered_daily and "total_open" in payload:
        return _daily_digest_body(m, payload)

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


def _text_body(event: NotificationEvent, payload: dict[str, Any]) -> str:
    m = _meta(event)
    lines = [m["subject"], ""]
    if m["intro"]:
        lines += [m["intro"], ""]
    for k, v in _labeled_rows(payload).items():
        lines.append(f"{k}: {v}")
    if m["action"]:
        lines += ["", f"Acción recomendada: {m['action']}"]
    lines += ["", f"{tpl.BRAND_NAME}."]
    return "\n".join(lines)
