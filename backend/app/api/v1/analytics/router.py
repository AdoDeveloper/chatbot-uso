from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_perm
from app.core.permissions import P
from app.db.session import get_db
from app.schemas.analytics import (
    AnalyticsChannels,
    AnalyticsDashboard,
    AnalyticsDevices,
    AnalyticsFeedback,
    AnalyticsHeatmap,
    AnalyticsLatencyTimeSeries,
    AnalyticsPages,
    AnalyticsRoutes,
    AnalyticsSourceQuality,
    AnalyticsTimeSeries,
    AnalyticsTimeline,
    AnalyticsTopics,
    CacheStats,
    PeriodComparison,
)
from app.services.monitoring import analytics as svc

router = APIRouter(prefix="/analytics", tags=["analytics"])

_SourceQ = Query("production", pattern="^(production|playground)$")


def _effective_days(
    days: int,
    date_from: datetime | None,
    date_to: datetime | None,
) -> int:
    """Convierte un rango de fechas personalizado al número de días equivalente."""
    if date_from is None:
        return days
    end = date_to or datetime.now(timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    start = date_from.replace(tzinfo=timezone.utc) if date_from.tzinfo is None else date_from
    return max(1, min(365, (end - start).days + 1))


@router.get("/dashboard", response_model=AnalyticsDashboard)
async def dashboard(
    source: str = _SourceQ,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.ANALYTICS_READ)),
):
    return await svc.get_dashboard(db, source=source)


@router.get("/topics", response_model=AnalyticsTopics)
async def topics(
    days: int = Query(7, ge=1, le=90),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    source: str = _SourceQ,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.ANALYTICS_READ)),
):
    return await svc.get_topics(db, days=_effective_days(days, date_from, date_to), source=source)


@router.get("/heatmap", response_model=AnalyticsHeatmap)
async def heatmap(
    window: str = Query("week", pattern="^(day|week|month|year)$"),
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.ANALYTICS_READ)),
):
    return await svc.get_heatmap(db, window=window)


@router.get("/devices", response_model=AnalyticsDevices)
async def devices(
    days: int = Query(30, ge=1, le=365),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    source: str = _SourceQ,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.ANALYTICS_READ)),
):
    return await svc.get_devices(db, days=_effective_days(days, date_from, date_to), source=source)


@router.get("/timeseries", response_model=AnalyticsTimeSeries)
async def timeseries(
    days: int = Query(30, ge=1, le=365),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    source: str = _SourceQ,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.ANALYTICS_READ)),
):
    return await svc.get_timeseries(db, days=_effective_days(days, date_from, date_to), source=source)


@router.get("/routes", response_model=AnalyticsRoutes)
async def routes(
    days: int = Query(30, ge=1, le=90),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    source: str = _SourceQ,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.ANALYTICS_READ)),
):
    return await svc.get_route_distribution(db, days=_effective_days(days, date_from, date_to), source=source)


@router.get("/latency/timeseries", response_model=AnalyticsLatencyTimeSeries)
async def latency_timeseries(
    days: int = Query(30, ge=1, le=365),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.ANALYTICS_READ)),
):
    return await svc.get_latency_timeseries(db, days=_effective_days(days, date_from, date_to))


@router.get("/sources/quality", response_model=AnalyticsSourceQuality)
async def source_quality(
    days: int = Query(30, ge=1, le=365),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.ANALYTICS_READ)),
):
    return await svc.get_source_quality(db, days=_effective_days(days, date_from, date_to))


@router.get("/timeline", response_model=AnalyticsTimeline)
async def timeline(
    days: int = Query(7, ge=1, le=90),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.ANALYTICS_READ)),
):
    return await svc.get_timeline(db, days=_effective_days(days, date_from, date_to), limit=limit)


@router.get("/comparison", response_model=PeriodComparison)
async def period_comparison(
    days: int = Query(7, ge=1, le=90),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    source: str = _SourceQ,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.ANALYTICS_READ)),
):
    return await svc.get_period_comparison(db, days=_effective_days(days, date_from, date_to), source=source)


@router.get("/channels", response_model=AnalyticsChannels)
async def channels(
    days: int = Query(7, ge=1, le=90),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.ANALYTICS_READ)),
):
    return await svc.get_channels(db, days=_effective_days(days, date_from, date_to))


@router.get("/pages", response_model=AnalyticsPages)
async def pages(
    days: int = Query(30, ge=1, le=365),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    source: str = _SourceQ,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.ANALYTICS_READ)),
):
    return await svc.get_pages(db, days=_effective_days(days, date_from, date_to), source=source)


@router.get("/feedback", response_model=AnalyticsFeedback)
async def feedback(
    days: int = Query(30, ge=1, le=365),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    source: str = _SourceQ,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.ANALYTICS_READ)),
):
    return await svc.get_feedback(db, days=_effective_days(days, date_from, date_to), source=source)


@router.get("/cache", response_model=CacheStats)
async def cache_stats(
    days: int = Query(7, ge=1, le=90),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.ANALYTICS_READ)),
):
    return await svc.get_cache_stats(db, days=_effective_days(days, date_from, date_to))


@router.post("/export")
async def export_analytics(
    body: dict,
    format: str = Query("xlsx", pattern="^(xlsx|pdf)$"),
    _: object = Depends(require_perm(P.ANALYTICS_READ)),
):
    from app.services.ingestion.export import excel_response, pdf_response
    rows = body.get("rows", [])
    if format == "pdf":
        return pdf_response(rows, "estadisticas", title="Estadísticas del Chatbot")
    return excel_response(rows, "estadisticas", sheet_name="Estadísticas")


_REPORT_TYPES = Literal["ejecutivo", "uso", "escalamientos", "conocimiento"]

_REPORT_META = {
    "ejecutivo":     ("Reporte Ejecutivo",                "ejecutivo"),
    "uso":           ("Reporte de Uso y Temas",           "uso-temas"),
    "escalamientos": ("Reporte de Escalamientos",         "escalamientos"),
    "conocimiento":  ("Reporte de Base de Conocimiento",  "conocimiento"),
}


def _fmt_delta(val: float | None) -> str:
    if val is None:
        return "N/D"
    sign = "+" if val >= 0 else ""
    return f"{sign}{val:.1f}%"


# Mismas etiquetas que usa el panel de escalamientos, para que el reporte
# hable el mismo idioma que la UI.
_TRIGGER_LABELS = {
    "no_answer": "Sin respuesta",
    "user_request": "Solicitud del usuario",
    "negative_feedback": "Valoración negativa",
    "keyword_detected": "Palabra crítica",
    "confidence_below": "Confianza baja",
    "loop_detected": "Bucle de respuestas",
    "manual": "Manual",
}


async def _get_unanswered_summary(
    db: AsyncSession, days: int, until: datetime | None = None,
) -> dict:
    """Resumen de preguntas sin responder en la ventana del reporte."""
    from sqlalchemy import func, select
    from app.models.unanswered_question import UnansweredQuestion

    _until = until or datetime.now(timezone.utc)
    since = _until - timedelta(days=days)

    total = (await db.execute(
        select(func.count(UnansweredQuestion.id))
        .where(UnansweredQuestion.created_at >= since)
        .where(UnansweredQuestion.created_at < _until)
    )).scalar_one()

    topic_rows = (await db.execute(
        select(UnansweredQuestion.detected_topic, func.count(UnansweredQuestion.id).label("n"))
        .where(UnansweredQuestion.created_at >= since)
        .where(UnansweredQuestion.created_at < _until)
        .where(UnansweredQuestion.detected_topic.isnot(None))
        .where(UnansweredQuestion.detected_topic != "")
        .group_by(UnansweredQuestion.detected_topic)
        .order_by(func.count(UnansweredQuestion.id).desc())
        .limit(10)
    )).all()

    recent_rows = (await db.execute(
        select(UnansweredQuestion.question, UnansweredQuestion.created_at)
        .where(UnansweredQuestion.created_at >= since)
        .where(UnansweredQuestion.created_at < _until)
        .order_by(UnansweredQuestion.created_at.desc())
        .limit(10)
    )).all()

    return {
        "total": total,
        "topics": [(t, n) for t, n in topic_rows],
        "recent": [(q, ts) for q, ts in recent_rows],
    }


async def _build_report_sections(
    report_type: str,
    days: int,
    source: str,
    db: AsyncSession,
    until: datetime | None = None,
) -> list[dict]:
    """Devuelve una lista de secciones: [{"title": str, "rows": list[dict]}]."""

    sections: list[dict] = []

    if report_type == "ejecutivo":
        comp = await svc.get_period_comparison(db, days=days, source=source, until=until)
        if comp:
            c, p = comp.current, comp.previous
            curr_label = f"{c.range_start} a {c.range_end}"
            prev_label = f"{p.range_start} a {p.range_end}"
            sections.append({
                "title": "COMPARATIVA DE PERÍODOS",
                "rows": [
                    {
                        "Métrica": "Consultas totales",
                        curr_label: c.queries,
                        prev_label: p.queries,
                        "Variación": _fmt_delta(comp.deltas.get("queries")),
                    },
                    {
                        "Métrica": "Sesiones únicas",
                        curr_label: c.unique_sessions,
                        prev_label: p.unique_sessions,
                        "Variación": _fmt_delta(comp.deltas.get("unique_sessions")),
                    },
                    {
                        "Métrica": "Tasa de resolución (%)",
                        curr_label: f"{c.resolution_rate:.1f}",
                        prev_label: f"{p.resolution_rate:.1f}",
                        "Variación": _fmt_delta(comp.deltas.get("resolution_rate")),
                    },
                    {
                        "Métrica": "Latencia promedio (ms)",
                        curr_label: f"{c.avg_latency_ms:.0f}",
                        prev_label: f"{p.avg_latency_ms:.0f}",
                        "Variación": _fmt_delta(comp.deltas.get("avg_latency_ms")),
                    },
                    {
                        "Métrica": "Latencia P95 (ms)",
                        curr_label: f"{c.p95_latency_ms:.0f}",
                        prev_label: f"{p.p95_latency_ms:.0f}",
                        "Variación": _fmt_delta(comp.deltas.get("p95_latency_ms")),
                    },
                ],
            })

        ts = await svc.get_timeseries(db, days=days, source=source, until=until)
        sections.append({
            "title": "TENDENCIA DIARIA DE CONSULTAS",
            "rows": [{"Fecha": pt.date, "Consultas": pt.count} for pt in ts.points],
            "chart": {"type": "line", "label": "Fecha", "value": "Consultas"},
        })

        topics = await svc.get_topics(db, days=days, source=source, until=until)
        sections.append({
            "title": "TEMAS PRINCIPALES (TOP 10)",
            "rows": [
                {
                    "#": i + 1,
                    "Tema": t.topic,
                    "Consultas": t.count,
                    "Tasa de resolución (%)": f"{t.resolution_rate:.1f}",
                }
                for i, t in enumerate(topics.topics[:10])
            ],
            "chart": {"type": "bar", "label": "Tema", "value": "Consultas"},
        })

        fb = await svc.get_feedback(db, days=days, source=source, until=until)
        sections.append({
            "title": "SATISFACCIÓN DE USUARIOS",
            "rows": [{
                "Período": f"{days} días",
                "Reacciones positivas": fb.summary.positive,
                "Reacciones negativas": fb.summary.negative,
                "Total reacciones": fb.summary.total,
                "Tasa positiva (%)": f"{fb.summary.positive_rate:.1f}",
            }],
            "chart": {"type": "pie", "columns": ["Reacciones positivas", "Reacciones negativas"]},
        })

        from app.services.escalation.metrics import get_metrics
        esc = await get_metrics(db, days=days, until=until)
        res_rate = esc.get("resolution_rate")
        avg_sec = esc.get("avg_resolution_seconds")
        csat = esc.get("csat_avg")
        esc_total = esc.get("total", 0)
        by_status = esc.get("by_status", {})
        total_queries = comp.current.queries if comp else 0
        # Tasa de contención: porcentaje de conversaciones resueltas sin
        # intervención humana.
        containment = (
            f"{max(0.0, (1 - esc_total / total_queries) * 100):.1f}"
            if total_queries > 0 else "N/D"
        )
        sections.append({
            "title": "RESUMEN DE ESCALAMIENTOS",
            "rows": [
                {"Métrica": "Tasa de contención (%)",     "Valor": containment},
                {"Métrica": "Total escalamientos",        "Valor": esc_total},
                {"Métrica": "Resueltos",                  "Valor": esc.get("resolved_count", 0)},
                {"Métrica": "Pendientes",                 "Valor": by_status.get("escalated", 0)},
                {"Métrica": "Tasa de resolución (%)",     "Valor": f"{res_rate * 100:.1f}" if res_rate is not None else "N/D"},
                {"Métrica": "Tiempo promedio resolución", "Valor": f"{avg_sec / 3600:.1f} h" if avg_sec is not None else "N/D"},
                {"Métrica": "CSAT promedio (1 a 5)",      "Valor": f"{csat:.2f}" if csat is not None else "N/D"},
            ],
        })

        by_trigger = esc.get("by_trigger", {})
        if by_trigger:
            sections.append({
                "title": "MOTIVOS DE ESCALAMIENTO",
                "rows": [
                    {"Motivo": _TRIGGER_LABELS.get(trig, trig), "Cantidad": n}
                    for trig, n in sorted(by_trigger.items(), key=lambda x: -x[1])
                ],
                "chart": {"type": "bar", "label": "Motivo", "value": "Cantidad"},
            })

        summary_parts: list[str] = []
        if comp:
            c = comp.current
            delta_q = comp.deltas.get("queries")
            delta_txt = (
                f", {'un aumento' if delta_q >= 0 else 'una disminución'} del {abs(delta_q):.1f}% respecto al período anterior"
                if delta_q is not None else ""
            )
            summary_parts.append(
                f"Durante el período se registraron {c.queries} consultas en "
                f"{c.unique_sessions} sesiones únicas{delta_txt}. "
                f"La tasa de resolución fue del {c.resolution_rate:.1f}% con una "
                f"latencia promedio de {c.avg_latency_ms / 1000:.1f} segundos."
            )
        if topics.topics:
            top = topics.topics[0]
            summary_parts.append(
                f"El tema más consultado fue «{top.topic}» con {top.count} consultas."
            )
        if fb.summary.total > 0:
            summary_parts.append(
                f"Los usuarios valoraron {fb.summary.total} respuestas, "
                f"con un {fb.summary.positive_rate:.1f}% de reacciones positivas."
            )
        if containment != "N/D":
            summary_parts.append(
                f"La tasa de contención fue del {containment}%: "
                f"{esc_total} conversaciones requirieron atención humana"
                + (f", de las cuales {esc.get('resolved_count', 0)} ya fueron resueltas." if esc_total else ".")
            )
        if summary_parts:
            sections.insert(0, {
                "title": "RESUMEN EJECUTIVO",
                "text": " ".join(summary_parts),
            })

        unanswered = await _get_unanswered_summary(db, days, until=until)
        if unanswered["total"] > 0:
            sections.append({
                "title": f"PREGUNTAS SIN RESPONDER ({unanswered['total']} en el período)",
                "rows": [
                    {"#": i + 1, "Tema": t, "Cantidad": n}
                    for i, (t, n) in enumerate(unanswered["topics"])
                ] or [{"Aviso": "Sin tema clasificado para las preguntas pendientes"}],
            })
            if unanswered["recent"]:
                sections.append({
                    "title": "PREGUNTAS SIN RESPONDER MÁS RECIENTES",
                    "rows": [
                        {"Pregunta": q, "Fecha": ts.strftime("%Y-%m-%d %H:%M") if ts else ""}
                        for q, ts in unanswered["recent"]
                    ],
                })

    elif report_type == "uso":
        ts = await svc.get_timeseries(db, days=days, source=source, until=until)
        total_q = sum(pt.count for pt in ts.points)
        peak = max(ts.points, key=lambda p: p.count, default=None)
        if ts.points:
            sections.append({
                "title": "RESUMEN",
                "text": (
                    f"Se registraron {total_q} consultas en el período, con un "
                    f"promedio de {total_q / max(len(ts.points), 1):.1f} por día. "
                    + (f"El día de mayor actividad fue el {peak.date} con {peak.count} consultas." if peak else "")
                ),
            })
        sections.append({
            "title": "TENDENCIA DIARIA DE CONSULTAS",
            "rows": [{"Fecha": pt.date, "Consultas": pt.count} for pt in ts.points],
            "chart": {"type": "line", "label": "Fecha", "value": "Consultas"},
        })

        topics = await svc.get_topics(db, days=days, source=source, until=until)
        sections.append({
            "title": "TEMAS CONSULTADOS",
            "rows": [
                {
                    "#": i + 1,
                    "Tema": t.topic,
                    "Consultas": t.count,
                    "Tasa de resolución (%)": f"{t.resolution_rate:.1f}",
                }
                for i, t in enumerate(topics.topics)
            ],
            "chart": {"type": "bar", "label": "Tema", "value": "Consultas"},
        })

        fb = await svc.get_feedback(db, days=days, source=source, until=until)
        if fb.trend:
            sections.append({
                "title": "TENDENCIA DE SATISFACCIÓN (REACCIONES POR DÍA)",
                "rows": [
                    {"Fecha": pt.date, "Positivas": pt.positive, "Negativas": pt.negative}
                    for pt in fb.trend
                ],
            })

        devices = await svc.get_devices(db, days=days, source=source, until=until)
        if devices.devices:
            sections.append({
                "title": "DISTRIBUCIÓN POR DISPOSITIVO",
                "rows": [
                    {"Dispositivo": d.device, "Consultas": d.count, "Porcentaje (%)": f"{d.percentage:.1f}"}
                    for d in devices.devices
                ],
                "chart": {"type": "pie", "label": "Dispositivo", "value": "Consultas"},
            })

        channels = await svc.get_channels(db, days=days, until=until)
        if channels.channels:
            sections.append({
                "title": "DISTRIBUCIÓN POR CANAL DE ENTRADA",
                "rows": [
                    {"Canal": ch.channel, "Consultas": ch.count, "Porcentaje (%)": f"{ch.percentage:.1f}"}
                    for ch in channels.channels
                ],
                "chart": {"type": "pie", "label": "Canal", "value": "Consultas"},
            })

    elif report_type == "escalamientos":
        from app.services.escalation.metrics import get_metrics
        esc = await get_metrics(db, days=days, until=until)
        res_rate = esc.get("resolution_rate")
        avg_sec = esc.get("avg_resolution_seconds")
        csat = esc.get("csat_avg")
        esc_total = esc.get("total", 0)
        by_status = esc.get("by_status", {})

        ts = await svc.get_timeseries(db, days=days, source=source, until=until)
        total_queries = sum(pt.count for pt in ts.points)
        containment = (
            f"{max(0.0, (1 - esc_total / total_queries) * 100):.1f}"
            if total_queries > 0 else "N/D"
        )

        sections.append({
            "title": "INDICADORES PRINCIPALES",
            "rows": [
                {"Métrica": "Tasa de contención (%)",     "Valor": containment},
                {"Métrica": "Total escalamientos",        "Valor": esc_total},
                {"Métrica": "Resueltos",                  "Valor": esc.get("resolved_count", 0)},
                {"Métrica": "Pendientes",                 "Valor": by_status.get("escalated", 0)},
                {"Métrica": "Tasa de resolución (%)",     "Valor": f"{res_rate * 100:.1f}" if res_rate is not None else "N/D"},
                {"Métrica": "Tiempo promedio resolución", "Valor": f"{avg_sec / 3600:.1f} h" if avg_sec is not None else "N/D"},
                {"Métrica": "CSAT promedio (1 a 5)",      "Valor": f"{csat:.2f}" if csat is not None else "N/D"},
            ],
        })

        if esc_total or total_queries:
            resolved = esc.get("resolved_count", 0)
            sections.insert(0, {
                "title": "RESUMEN",
                "text": (
                    f"De {total_queries} consultas del período, {esc_total} conversaciones "
                    f"escalaron a atención humana"
                    + (f", con una tasa de contención del {containment}%" if containment != "N/D" else "")
                    + f". Se resolvieron {resolved}"
                    + (f", con un tiempo promedio de {avg_sec / 3600:.1f} horas" if avg_sec is not None else "")
                    + (f" y una satisfacción promedio de {csat:.2f} sobre 5." if csat is not None else ".")
                ),
            })

        if by_status:
            sections.append({
                "title": "DESGLOSE POR ESTADO",
                "rows": [
                    {"Estado": state, "Cantidad": count}
                    for state, count in by_status.items()
                ],
                "chart": {"type": "pie", "label": "Estado", "value": "Cantidad"},
            })

        by_trigger = esc.get("by_trigger", {})
        if by_trigger:
            sections.append({
                "title": "MOTIVOS DE ESCALAMIENTO",
                "rows": [
                    {"Motivo": _TRIGGER_LABELS.get(trig, trig), "Cantidad": n}
                    for trig, n in sorted(by_trigger.items(), key=lambda x: -x[1])
                ],
                "chart": {"type": "bar", "label": "Motivo", "value": "Cantidad"},
            })

    elif report_type == "conocimiento":
        from sqlalchemy import func, select
        from app.models.enums import ReviewStatus
        from app.models.source import Source

        status_rows = (await db.execute(
            select(Source.review_status, func.count(Source.id), func.coalesce(func.sum(Source.chunk_count), 0))
            .where(Source.deleted_at.is_(None))
            .group_by(Source.review_status)
        )).all()
        by_review = {row[0]: (int(row[1]), int(row[2])) for row in status_rows}
        total_sources = sum(n for n, _ in by_review.values())
        total_chunks = sum(c for _, c in by_review.values())
        approved = by_review.get(ReviewStatus.aprobada, (0, 0))
        pending = by_review.get(ReviewStatus.pendiente_revision, (0, 0))

        sections.append({
            "title": "RESUMEN",
            "text": (
                f"La base de conocimiento contiene {total_sources} fuentes con "
                f"{total_chunks} fragmentos indexados. {approved[0]} fuentes están "
                f"aprobadas y visibles para responder consultas"
                + (f", y {pending[0]} esperan revisión." if pending[0] else ".")
            ),
        })

        _REVIEW_LABELS = {
            ReviewStatus.aprobada: "Aprobadas",
            ReviewStatus.pendiente_revision: "Pendientes de revisión",
            ReviewStatus.rechazada: "Rechazadas",
            ReviewStatus.procesando: "En procesamiento",
        }
        sections.append({
            "title": "FUENTES POR ESTADO DE REVISIÓN",
            "rows": [
                {"Estado": _REVIEW_LABELS.get(st, str(st)), "Fuentes": n, "Fragmentos": c}
                for st, (n, c) in sorted(by_review.items(), key=lambda x: -x[1][0])
            ],
            "chart": {"type": "pie", "label": "Estado", "value": "Fuentes"},
        })

        quality = await svc.get_source_quality(db, days=days)
        if quality.sources:
            sections.append({
                "title": "FUENTES MÁS UTILIZADAS EN LAS RESPUESTAS",
                "rows": [
                    {"#": i + 1, "Fuente": s.source_name,
                     "Veces citada": s.retrieval_count,
                     "Relevancia promedio": f"{s.avg_score:.2f}"}
                    for i, s in enumerate(quality.sources[:10])
                ],
                "chart": {"type": "bar", "label": "Fuente", "value": "Veces citada"},
            })

        used_names = {s.source_name for s in quality.sources}
        unused_rows = (await db.execute(
            select(Source.name, Source.chunk_count)
            .where(Source.deleted_at.is_(None))
            .where(Source.review_status == ReviewStatus.aprobada)
            .where(Source.chunk_count > 0)
            .where(Source.name.notin_(used_names) if used_names else Source.chunk_count > 0)
            .order_by(Source.name)
            .limit(15)
        )).all()
        if unused_rows:
            sections.append({
                "title": "FUENTES APROBADAS SIN USO EN EL PERÍODO",
                "rows": [
                    {"Fuente": name, "Fragmentos": int(chunks or 0)}
                    for name, chunks in unused_rows
                ],
            })

        unanswered = await _get_unanswered_summary(db, days, until=until)
        if unanswered["total"] > 0:
            sections.append({
                "title": f"PREGUNTAS SIN RESPONDER EN EL PERÍODO ({unanswered['total']})",
                "rows": [
                    {"#": i + 1, "Tema": t, "Cantidad": n}
                    for i, (t, n) in enumerate(unanswered["topics"])
                ] or [{"Aviso": "Sin tema clasificado para las preguntas pendientes"}],
                "chart": {"type": "bar", "label": "Tema", "value": "Cantidad"},
            })
            if unanswered["recent"]:
                sections.append({
                    "title": "PREGUNTAS SIN RESPONDER MÁS RECIENTES",
                    "rows": [
                        {"Pregunta": q, "Fecha": ts.strftime("%Y-%m-%d %H:%M") if ts else ""}
                        for q, ts in unanswered["recent"]
                    ],
                })

    return sections


@router.post("/reports")
async def generate_report(
    report_type: _REPORT_TYPES,
    date_from: date = Query(...),
    date_to: date = Query(...),
    source: str = _SourceQ,
    db: AsyncSession = Depends(get_db),
    _: object = Depends(require_perm(P.ANALYTICS_READ)),
):
    """Genera y descarga un reporte PDF del rango de fechas indicado."""
    from app.services.ingestion.export import pdf_report_response

    if date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La fecha inicial no puede ser posterior a la final.",
        )
    days = (date_to - date_from).days + 1
    if days > 366:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El rango no puede superar un año.",
        )
    until = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=timezone.utc)

    title, filename_base = _REPORT_META.get(report_type, ("Reporte", report_type))
    subtitle = f"Período: {date_from.strftime('%d/%m/%Y')} al {date_to.strftime('%d/%m/%Y')}"

    sections = await _build_report_sections(report_type, days, source, db, until=until)
    filename = f"{filename_base}-{date_to.isoformat()}"
    return pdf_report_response(sections, filename, title=title, subtitle=subtitle)
