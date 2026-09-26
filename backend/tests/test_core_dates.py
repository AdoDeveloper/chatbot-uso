from datetime import datetime, timezone

from app.core.dates import since_until


def test_calendar_days_are_el_salvador_days():
    since, until = since_until(datetime(2026, 9, 1), datetime(2026, 9, 10))

    assert since == datetime(2026, 9, 1, 6, 0, tzinfo=timezone.utc)
    assert until == datetime(2026, 9, 11, 5, 59, 59, 999999, tzinfo=timezone.utc)


def test_aware_values_keep_their_zone():
    start = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)

    since, _ = since_until(start, None)

    assert since == start


def test_without_start_there_is_no_range():
    assert since_until(None, datetime(2026, 9, 1)) == (None, None)
