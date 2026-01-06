from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from typing import Iterator


class Time:
    _mocked_current_time = None

    @staticmethod
    def now() -> datetime:
        if Time._mocked_current_time is not None:
            return Time._mocked_current_time
        return datetime.now(timezone.utc)

    @contextmanager
    @staticmethod
    def mock_current_time(time: datetime, offset_hours: int = 0) -> Iterator[datetime]:
        if Time._mocked_current_time is not None:
            raise RuntimeError("Another mock for the current time is already in scope.")

        mock_time = time + timedelta(hours=offset_hours)
        Time._mocked_current_time = mock_time
        try:
            yield mock_time
        finally:
            Time._mocked_current_time = None
