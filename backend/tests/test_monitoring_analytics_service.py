"""Tests unitarios directos de app/services/monitoring/analytics.py.

Los tests de router (test_analytics_router_extra.py, test_analytics_timeline.py)
ya cubren la capa HTTP (auth, shape de respuesta, parseo de query params) para
la mayoría de endpoints via smoke tests parametrizados. Este archivo llama las
funciones del servicio directamente con `db_session`, sembrando datos reales,
para ejercitar las ramas internas de agregación que esos smoke tests no
disparan: casos sin datos, ceros, redondeo, clasificación de canal, feedback
positivo/negativo, calidad de fuentes, comparación de períodos, etc.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.chat_conversation import ChatConversation
from app.models.chat_message import ChatMessage
from app.models.enums import (
    ConversationStatus,
    MessageFeedback,
    MessageRole,
    SourceStatus,
    SourceType,
    UnansweredStatus,
)
from app.models.source import Source
from app.models.unanswered_question import UnansweredQuestion
from app.services.monitoring import analytics as svc

NOW = datetime.now(timezone.utc)


def _conv(**kwargs) -> ChatConversation:
    defaults = dict(
        id=uuid.uuid4(),
        session_id=f"sess-{uuid.uuid4().hex[:8]}",
        started_at=NOW,
        last_message_at=NOW,
    )
    defaults.update(kwargs)
    return ChatConversation(**defaults)


def _msg(conversation_id, **kwargs) -> ChatMessage:
    defaults = dict(
        id=uuid.uuid4(),
        conversation_id=conversation_id,
        role=MessageRole.user,
        content="hola",
        created_at=NOW,
    )
    defaults.update(kwargs)
    return ChatMessage(**defaults)


class TestGetChannels:
    async def test_no_data_returns_empty(self, db_session):
        result = await svc.get_channels(db_session, days=7)
        assert result.channels == []
        assert result.days == 7

    async def test_classifies_widget_api_and_playground(self, db_session):
        widget = _conv(origin_url="https://uso.edu/inicio", browser="Chrome")
        api = _conv(origin_url=None, browser=None)
        playground = _conv(origin_url="https://uso.edu/panel", browser="playground")
        db_session.add_all([widget, api, playground])
        await db_session.commit()

        result = await svc.get_channels(db_session, days=7)
        by_channel = {c.channel: c for c in result.channels}
        assert by_channel["widget"].count == 1
        assert by_channel["api"].count == 1
        assert by_channel["playground"].count == 1
        # percentages sum to 100 (three equal buckets of 1/3)
        total_pct = sum(c.percentage for c in result.channels)
        assert round(total_pct, 0) == 100

    async def test_respects_until_and_since_window(self, db_session):
        old = _conv(origin_url="https://uso.edu/x", started_at=NOW - timedelta(days=60))
        recent = _conv(origin_url="https://uso.edu/y", started_at=NOW)
        db_session.add_all([old, recent])
        await db_session.commit()

        result = await svc.get_channels(db_session, days=7, until=NOW + timedelta(seconds=1))
        assert sum(c.count for c in result.channels) == 1


class TestGetCacheStats:
    async def test_no_data_zero_hit_rate(self, db_session):
        result = await svc.get_cache_stats(db_session, days=7)
        assert result.hits == 0
        assert result.misses == 0
        assert result.hit_rate == 0.0
        assert result.days == 7

    async def test_hits_and_misses_computed(self, db_session):
        conv = _conv()
        db_session.add(conv)
        await db_session.flush()
        db_session.add_all([
            _msg(conv.id, role=MessageRole.assistant, rag_route="cache_semantic"),
            _msg(conv.id, role=MessageRole.assistant, rag_route="cache_exact"),
            _msg(conv.id, role=MessageRole.assistant, rag_route="rag_full"),
        ])
        await db_session.commit()

        result = await svc.get_cache_stats(db_session, days=7)
        assert result.hits == 2
        assert result.misses == 1
        assert result.hit_rate == round(2 / 3 * 100, 2)

    async def test_null_rag_route_excluded_from_misses(self, db_session):
        conv = _conv()
        db_session.add(conv)
        await db_session.flush()
        db_session.add(_msg(conv.id, role=MessageRole.assistant, rag_route=None))
        await db_session.commit()

        result = await svc.get_cache_stats(db_session, days=7)
        assert result.hits == 0
        assert result.misses == 0
        assert result.hit_rate == 0.0


class TestGetPages:
    async def test_no_data_returns_empty(self, db_session):
        result = await svc.get_pages(db_session, days=30)
        assert result.pages == []
        assert result.days == 30

    async def test_collapses_query_string_variants(self, db_session):
        c1 = _conv(origin_url="https://uso.edu/inicio?utm=a")
        c2 = _conv(origin_url="https://uso.edu/inicio?utm=b")
        c3 = _conv(origin_url="https://uso.edu/inicio/")
        db_session.add_all([c1, c2, c3])
        await db_session.commit()

        result = await svc.get_pages(db_session, days=30)
        assert len(result.pages) == 1
        assert result.pages[0].page == "https://uso.edu/inicio"
        assert result.pages[0].count == 3
        assert result.pages[0].percentage == 100.0

    async def test_excludes_playground_source_by_default(self, db_session):
        pg = _conv(origin_url="https://uso.edu/panel", browser="playground")
        db_session.add(pg)
        await db_session.commit()

        result = await svc.get_pages(db_session, days=30, source="production")
        assert result.pages == []

        result_pg = await svc.get_pages(db_session, days=30, source="playground")
        assert len(result_pg.pages) == 1

    async def test_malformed_url_falls_back_to_raw(self, db_session):
        # A pathological origin_url that urlparse still handles but produces
        # an empty scheme://netloc+path combination other than raw fallback.
        conv = _conv(origin_url="not-a-valid-url")
        db_session.add(conv)
        await db_session.commit()

        result = await svc.get_pages(db_session, days=30)
        assert len(result.pages) == 1
        assert result.pages[0].count == 1


class TestGetFeedback:
    async def test_no_data_zero_rate_empty_trend(self, db_session):
        result = await svc.get_feedback(db_session, days=30)
        assert result.summary.positive == 0
        assert result.summary.negative == 0
        assert result.summary.total == 0
        assert result.summary.positive_rate == 0.0
        assert result.trend == []

    async def test_positive_and_negative_counts_and_rate(self, db_session):
        conv = _conv()
        db_session.add(conv)
        await db_session.flush()
        db_session.add_all([
            _msg(conv.id, role=MessageRole.assistant, feedback=MessageFeedback.positive),
            _msg(conv.id, role=MessageRole.assistant, feedback=MessageFeedback.positive),
            _msg(conv.id, role=MessageRole.assistant, feedback=MessageFeedback.negative),
        ])
        await db_session.commit()

        result = await svc.get_feedback(db_session, days=30)
        assert result.summary.positive == 2
        assert result.summary.negative == 1
        assert result.summary.total == 3
        assert result.summary.positive_rate == round(2 / 3 * 100, 1)

    async def test_trend_groups_by_day(self, db_session):
        conv = _conv()
        db_session.add(conv)
        await db_session.flush()
        yesterday = NOW - timedelta(days=1)
        db_session.add_all([
            _msg(conv.id, role=MessageRole.assistant, feedback=MessageFeedback.positive, created_at=NOW),
            _msg(conv.id, role=MessageRole.assistant, feedback=MessageFeedback.negative, created_at=yesterday),
        ])
        await db_session.commit()

        result = await svc.get_feedback(db_session, days=30)
        assert len(result.trend) == 2
        by_date = {t.date: t for t in result.trend}
        assert any(t.positive == 1 for t in by_date.values())
        assert any(t.negative == 1 for t in by_date.values())

    async def test_messages_without_feedback_excluded(self, db_session):
        conv = _conv()
        db_session.add(conv)
        await db_session.flush()
        db_session.add(_msg(conv.id, role=MessageRole.assistant, feedback=None))
        await db_session.commit()

        result = await svc.get_feedback(db_session, days=30)
        assert result.summary.total == 0

    async def test_respects_until_window(self, db_session):
        conv = _conv()
        db_session.add(conv)
        await db_session.flush()
        old = NOW - timedelta(days=60)
        db_session.add(_msg(conv.id, role=MessageRole.assistant, feedback=MessageFeedback.positive, created_at=old))
        await db_session.commit()

        result = await svc.get_feedback(db_session, days=7, until=NOW)
        assert result.summary.total == 0


class TestGetSourceQuality:
    async def test_no_data_returns_empty(self, db_session):
        result = await svc.get_source_quality(db_session, days=30)
        assert result.sources == []
        assert result.days == 30

    async def test_aggregates_counts_and_avg_score(self, db_session):
        conv = _conv()
        db_session.add(conv)
        await db_session.flush()
        sid = str(uuid.uuid4())
        db_session.add_all([
            _msg(
                conv.id, role=MessageRole.assistant,
                sources_json=[{"source_id": sid, "source_name": "Reglamento", "score": 0.8}],
            ),
            _msg(
                conv.id, role=MessageRole.assistant,
                sources_json=[{"source_id": sid, "source_name": "Reglamento", "score": 0.6}],
            ),
        ])
        await db_session.commit()

        result = await svc.get_source_quality(db_session, days=30)
        assert len(result.sources) == 1
        s = result.sources[0]
        assert s.source_id == sid
        assert s.retrieval_count == 2
        assert s.avg_score == round((0.8 + 0.6) / 2, 4)

    async def test_ignores_entries_without_source_id(self, db_session):
        conv = _conv()
        db_session.add(conv)
        await db_session.flush()
        db_session.add(_msg(
            conv.id, role=MessageRole.assistant,
            sources_json=[{"source_name": "Sin id", "score": 0.5}],
        ))
        await db_session.commit()

        result = await svc.get_source_quality(db_session, days=30)
        assert result.sources == []

    async def test_invalid_score_defaults_gracefully(self, db_session):
        conv = _conv()
        db_session.add(conv)
        await db_session.flush()
        sid = str(uuid.uuid4())
        db_session.add(_msg(
            conv.id, role=MessageRole.assistant,
            sources_json=[{"source_id": sid, "source_name": "X", "score": "not-a-number"}],
        ))
        await db_session.commit()

        result = await svc.get_source_quality(db_session, days=30)
        assert len(result.sources) == 1
        assert result.sources[0].avg_score == 0.0

    async def test_non_list_sources_json_ignored(self, db_session):
        # sources_json defaults to list, but simulate a dict-shaped stray value
        # by directly constructing with a non-list (defensive branch: isinstance check).
        conv = _conv()
        db_session.add(conv)
        await db_session.flush()
        msg = _msg(conv.id, role=MessageRole.assistant, sources_json=[])
        db_session.add(msg)
        await db_session.commit()

        result = await svc.get_source_quality(db_session, days=30)
        assert result.sources == []


class TestSnapshotForRangeAndPeriodComparison:
    async def test_empty_range_snapshot_is_all_zero(self, db_session):
        snap = await svc._snapshot_for_range(
            db_session, range_start=NOW - timedelta(days=7), range_end=NOW,
        )
        assert snap.queries == 0
        assert snap.unique_sessions == 0
        assert snap.resolution_rate == 0.0
        assert snap.avg_latency_ms == 0.0
        assert snap.p95_latency_ms == 0.0

    async def test_snapshot_computes_queries_sessions_and_resolution(self, db_session):
        conv1 = _conv(status=ConversationStatus.active)
        conv2 = _conv(
            status=ConversationStatus.escalated,
            escalated_at=NOW,
        )
        db_session.add_all([conv1, conv2])
        await db_session.flush()
        db_session.add_all([
            _msg(conv1.id, role=MessageRole.user),
            _msg(conv1.id, role=MessageRole.assistant, latency_ms=1000),
            _msg(conv2.id, role=MessageRole.user),
            _msg(conv2.id, role=MessageRole.assistant, latency_ms=3000),
        ])
        await db_session.commit()

        snap = await svc._snapshot_for_range(
            db_session, range_start=NOW - timedelta(hours=1), range_end=NOW + timedelta(hours=1),
        )
        assert snap.queries == 2
        assert snap.unique_sessions == 2
        # 1 of 2 sessions escalated -> resolution rate 50%
        assert snap.resolution_rate == 50.0
        assert snap.avg_latency_ms == 2000.0

    async def test_period_comparison_deltas_with_previous_zero(self, db_session):
        """When the previous period has zero baseline, _delta returns 0.0
        instead of dividing by zero (b <= 0 branch)."""
        conv = _conv(started_at=NOW)
        db_session.add(conv)
        await db_session.flush()
        db_session.add(_msg(conv.id, role=MessageRole.user, created_at=NOW))
        await db_session.commit()

        result = await svc.get_period_comparison(db_session, days=7, until=NOW)
        assert result.current.queries == 1
        assert result.previous.queries == 0
        assert result.deltas["queries"] == 0.0
        assert result.deltas["resolution_rate"] == round(
            result.current.resolution_rate - result.previous.resolution_rate, 2
        )

    async def test_period_comparison_positive_delta(self, db_session):
        cur_conv = _conv(started_at=NOW)
        prev_conv = _conv(started_at=NOW - timedelta(days=10))
        db_session.add_all([cur_conv, prev_conv])
        await db_session.flush()
        # current period: 2 queries, previous: 1 query -> +100% delta
        db_session.add_all([
            _msg(cur_conv.id, role=MessageRole.user, created_at=NOW),
            _msg(cur_conv.id, role=MessageRole.user, created_at=NOW),
            _msg(prev_conv.id, role=MessageRole.user, created_at=NOW - timedelta(days=10)),
        ])
        await db_session.commit()

        result = await svc.get_period_comparison(db_session, days=7, until=NOW)
        assert result.current.queries == 2
        assert result.previous.queries == 1
        assert result.deltas["queries"] == 100.0


class TestClassifyChannel:
    def test_playground_browser_wins_regardless_of_origin(self):
        assert svc._classify_channel("https://uso.edu", "playground") == "playground"
        assert svc._classify_channel(None, "panel") == "playground"
        assert svc._classify_channel(None, "ADMIN") == "playground"

    def test_no_origin_is_api(self):
        assert svc._classify_channel(None, "Chrome") == "api"
        assert svc._classify_channel("", "Chrome") == "api"

    def test_origin_present_is_widget(self):
        assert svc._classify_channel("https://uso.edu/inicio", "Chrome") == "widget"


class TestGetTimeline:
    async def test_empty_returns_no_events(self, db_session):
        result = await svc.get_timeline(db_session, days=7)
        assert result.events == []
        assert result.days == 7

    async def test_events_sorted_desc_and_limited(self, db_session):
        older_src = Source(
            id=uuid.uuid4(), name="Fuente A", type=SourceType.pdf,
            status=SourceStatus.ready, chunk_count=1,
            updated_at=NOW - timedelta(hours=2),
        )
        newer_src = Source(
            id=uuid.uuid4(), name="Fuente B", type=SourceType.pdf,
            status=SourceStatus.ready, chunk_count=2,
            updated_at=NOW,
        )
        db_session.add_all([older_src, newer_src])
        await db_session.commit()

        result = await svc.get_timeline(db_session, days=7, limit=50)
        assert len(result.events) == 2
        # sorted descending by created_at
        assert result.events[0].id == f"source_ready:{newer_src.id}"
        assert result.events[1].id == f"source_ready:{older_src.id}"

    async def test_limit_truncates_events(self, db_session):
        srcs = [
            Source(
                id=uuid.uuid4(), name=f"Fuente {i}", type=SourceType.pdf,
                status=SourceStatus.ready, chunk_count=1,
                updated_at=NOW - timedelta(minutes=i),
            )
            for i in range(5)
        ]
        db_session.add_all(srcs)
        await db_session.commit()

        result = await svc.get_timeline(db_session, days=7, limit=2)
        assert len(result.events) == 2

    async def test_deleted_sources_excluded(self, db_session):
        deleted = Source(
            id=uuid.uuid4(), name="Borrada", type=SourceType.pdf,
            status=SourceStatus.ready, chunk_count=1,
            updated_at=NOW, deleted_at=NOW,
        )
        db_session.add(deleted)
        await db_session.commit()

        result = await svc.get_timeline(db_session, days=7)
        assert result.events == []


class TestGetTopics:
    async def test_no_data_returns_empty(self, db_session):
        result = await svc.get_topics(db_session, days=7)
        assert result.topics == []
        assert result.days == 7

    async def test_resolution_rate_computed_per_topic(self, db_session):
        conv = _conv()
        db_session.add(conv)
        await db_session.flush()
        db_session.add_all([
            UnansweredQuestion(
                id=uuid.uuid4(), conversation_id=conv.id, question="q1",
                detected_topic="matriculas", status=UnansweredStatus.resolved,
                created_at=NOW,
            ),
            UnansweredQuestion(
                id=uuid.uuid4(), conversation_id=conv.id, question="q2",
                detected_topic="matriculas", status=UnansweredStatus.open,
                created_at=NOW,
            ),
        ])
        await db_session.commit()

        result = await svc.get_topics(db_session, days=7)
        assert len(result.topics) == 1
        assert result.topics[0].topic == "matriculas"
        assert result.topics[0].count == 2
        assert result.topics[0].resolution_rate == 50.0

    async def test_topics_without_detected_topic_excluded(self, db_session):
        conv = _conv()
        db_session.add(conv)
        await db_session.flush()
        db_session.add(UnansweredQuestion(
            id=uuid.uuid4(), conversation_id=conv.id, question="q",
            detected_topic=None, status=UnansweredStatus.open, created_at=NOW,
        ))
        await db_session.commit()

        result = await svc.get_topics(db_session, days=7)
        assert result.topics == []


class TestGetDevices:
    async def test_no_data_returns_empty(self, db_session):
        result = await svc.get_devices(db_session, days=30)
        assert result.devices == []

    async def test_percentages_and_unknown_fallback(self, db_session):
        db_session.add_all([
            _conv(device="mobile"),
            _conv(device="mobile"),
            _conv(device="desktop"),
        ])
        await db_session.commit()

        result = await svc.get_devices(db_session, days=30)
        by_device = {d.device: d for d in result.devices}
        assert by_device["mobile"].count == 2
        assert by_device["mobile"].percentage == round(2 / 3 * 100, 1)
        assert by_device["desktop"].count == 1

    async def test_null_device_excluded(self, db_session):
        db_session.add(_conv(device=None))
        await db_session.commit()

        result = await svc.get_devices(db_session, days=30)
        assert result.devices == []


class TestGetRouteDistribution:
    async def test_no_data_returns_empty(self, db_session):
        result = await svc.get_route_distribution(db_session, days=30)
        assert result.routes == []
        assert result.days == 30

    async def test_percentages_computed(self, db_session):
        conv = _conv()
        db_session.add(conv)
        await db_session.flush()
        db_session.add_all([
            _msg(conv.id, role=MessageRole.assistant, rag_route="rag_full"),
            _msg(conv.id, role=MessageRole.assistant, rag_route="rag_full"),
            _msg(conv.id, role=MessageRole.assistant, rag_route="direct"),
        ])
        await db_session.commit()

        result = await svc.get_route_distribution(db_session, days=30)
        by_route = {r.route: r for r in result.routes}
        assert by_route["rag_full"].count == 2
        assert by_route["rag_full"].percentage == round(2 / 3 * 100, 1)


class TestGetLatencyTimeseries:
    async def test_no_data_returns_empty(self, db_session):
        result = await svc.get_latency_timeseries(db_session, days=30)
        assert result.points == []
        assert result.days == 30

    async def test_avg_and_p95_computed_per_day(self, db_session):
        conv = _conv()
        db_session.add(conv)
        await db_session.flush()
        db_session.add_all([
            _msg(conv.id, role=MessageRole.assistant, latency_ms=100, created_at=NOW),
            _msg(conv.id, role=MessageRole.assistant, latency_ms=200, created_at=NOW),
            _msg(conv.id, role=MessageRole.assistant, latency_ms=300, created_at=NOW),
        ])
        await db_session.commit()

        result = await svc.get_latency_timeseries(db_session, days=30)
        assert len(result.points) == 1
        point = result.points[0]
        assert point.avg_ms == 200.0
        assert point.p95_ms >= point.avg_ms

    async def test_playground_messages_excluded(self, db_session):
        conv = _conv(browser="playground")
        db_session.add(conv)
        await db_session.flush()
        db_session.add(_msg(conv.id, role=MessageRole.assistant, latency_ms=100, created_at=NOW))
        await db_session.commit()

        result = await svc.get_latency_timeseries(db_session, days=30)
        assert result.points == []


class TestGetDashboard:
    async def test_no_data_defaults(self, db_session):
        result = await svc.get_dashboard(db_session)
        assert result.queries_today == 0
        assert result.queries_week == 0
        assert result.active_sources == 0
        assert result.unanswered_pending == 0

    async def test_with_data_counts_and_active_sources(self, db_session):
        conv = _conv(started_at=NOW)
        db_session.add(conv)
        await db_session.flush()
        db_session.add(_msg(conv.id, role=MessageRole.user, created_at=NOW))
        src = Source(
            id=uuid.uuid4(), name="Activa", type=SourceType.pdf,
            status=SourceStatus.ready, chunk_count=1,
        )
        db_session.add(src)
        await db_session.commit()

        result = await svc.get_dashboard(db_session)
        assert result.queries_today == 1
        assert result.active_sources == 1

    async def test_playground_source_isolates_counts(self, db_session):
        conv = _conv(started_at=NOW, browser="playground")
        db_session.add(conv)
        await db_session.flush()
        db_session.add(_msg(conv.id, role=MessageRole.user, created_at=NOW))
        await db_session.commit()

        prod_result = await svc.get_dashboard(db_session, source="production")
        assert prod_result.queries_today == 0

        pg_result = await svc.get_dashboard(db_session, source="playground")
        assert pg_result.queries_today == 1


class TestGetHeatmap:
    async def test_day_window_empty(self, db_session):
        result = await svc.get_heatmap(db_session, window="day")
        assert result.cells == []
        assert result.window == "day"

    async def test_month_window_with_data(self, db_session):
        conv = _conv()
        db_session.add(conv)
        await db_session.flush()
        db_session.add(_msg(conv.id, role=MessageRole.user, created_at=NOW))
        await db_session.commit()

        result = await svc.get_heatmap(db_session, window="month")
        assert result.window == "month"
        assert len(result.cells) == 1
        assert result.cells[0].count == 1

    async def test_year_window(self, db_session):
        result = await svc.get_heatmap(db_session, window="year")
        assert result.window == "year"
        assert result.cells == []


class TestGetTimeseries:
    async def test_no_data_returns_empty(self, db_session):
        result = await svc.get_timeseries(db_session, days=30)
        assert result.points == []
        assert result.days == 30

    async def test_counts_per_day(self, db_session):
        conv = _conv()
        db_session.add(conv)
        await db_session.flush()
        db_session.add_all([
            _msg(conv.id, role=MessageRole.user, created_at=NOW),
            _msg(conv.id, role=MessageRole.user, created_at=NOW),
        ])
        await db_session.commit()

        result = await svc.get_timeseries(db_session, days=30)
        assert len(result.points) == 1
        assert result.points[0].count == 2
