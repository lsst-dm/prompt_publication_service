from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta


class DateTimeSource:
    _mocked_current_time: datetime | None = None

    @staticmethod
    def now() -> datetime:
        if DateTimeSource._mocked_current_time is not None:
            return DateTimeSource._mocked_current_time
        return datetime.now(UTC)

    @contextmanager
    @staticmethod
    def mock_current_time(time: datetime, offset_hours: int = 0) -> Iterator[datetime]:
        if DateTimeSource._mocked_current_time is not None:
            raise RuntimeError("Another mock for the current time is already in scope.")

        mock_time = time + timedelta(hours=offset_hours)
        DateTimeSource._mocked_current_time = mock_time
        try:
            yield mock_time
        finally:
            DateTimeSource._mocked_current_time = None
