import asyncio
from datetime import UTC, datetime, time, timedelta

# The earliest sunset on Cerro Pachon is in late June, around 10:30pm UTC.
# We stop an hour earlier to let tasks complete well before observing starts.
_OBSERVING_START_TIME = time(21, 30, tzinfo=UTC)
# Latest sunrise is around 11am UTC, and we wait an extra hour because data
# sometimes trickles in late or prompt processing falls behind.
_OBSERVING_END_TIME = time(12, 0, tzinfo=UTC)


def _get_next_allowed_start_time(current_datetime: datetime) -> datetime:
    current_date = current_datetime.astimezone(UTC).date()
    current_time = current_datetime.astimezone(UTC).time()
    if current_time > _OBSERVING_START_TIME:
        # It's before midnight, and we're in observing hours, so wait until
        # the end of observing hours in the morning.
        tomorrow = current_date + timedelta(days=1)
        return datetime.combine(tomorrow, _OBSERVING_END_TIME)
    elif current_time < _OBSERVING_END_TIME:
        # It's past midnight, and we're in observing hours, so wait until
        # the end of observing hours today.
        return datetime.combine(current_date, _OBSERVING_END_TIME)
    else:
        # We are outside of observing hours, tasks can start immediately.
        return current_datetime


def _calculate_seconds_until_allowed_start_time(current_datetime: datetime) -> float:
    start_time = _get_next_allowed_start_time(current_datetime)
    if start_time > current_datetime:
        return (start_time - current_datetime).total_seconds()
    else:
        return 0


async def wait_for_next_allowed_start_time() -> None:
    delay_time = _calculate_seconds_until_allowed_start_time(datetime.now(UTC))
    if delay_time > 0:
        await asyncio.sleep(delay_time)
