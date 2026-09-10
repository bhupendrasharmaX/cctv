"""
Shared `?from=`/`?to=` handling for the search endpoints.

Every investigative query is bounded by an incident window -- "where was this
vehicle between 09:00 and 12:00", not "everywhere it has ever been". Detections,
alerts and the cross-camera trace all take the same pair of parameters, parsed
and validated the same way, so an operator does not have to learn three
dialects.
"""

import datetime
from typing import NamedTuple, Optional

from fastapi import HTTPException, Query

from backend.app.models import to_naive_utc


class TimeWindow(NamedTuple):
    """Both bounds are inclusive, naive UTC, and either may be None."""
    start: Optional[datetime.datetime]
    end: Optional[datetime.datetime]

    @property
    def is_bounded(self) -> bool:
        return self.start is not None or self.end is not None

    def describe(self) -> Optional[str]:
        if not self.is_bounded:
            return None
        if self.start and self.end:
            return f"{self.start.isoformat()}Z to {self.end.isoformat()}Z"
        if self.start:
            return f"from {self.start.isoformat()}Z"
        return f"up to {self.end.isoformat()}Z"


FromParam = Query(
    None,
    alias="from",
    description="Start of the window, ISO-8601. An offset is honoured; without one the value is read as UTC.",
)
ToParam = Query(
    None,
    alias="to",
    description="End of the window, ISO-8601. An offset is honoured; without one the value is read as UTC.",
)


def resolve_window(
    from_time: Optional[datetime.datetime] = FromParam,
    to_time: Optional[datetime.datetime] = ToParam,
) -> TimeWindow:
    """
    FastAPI dependency producing a validated window.

    An inverted window is rejected rather than quietly returning nothing: an
    empty result looks identical to "this vehicle was never seen", which is the
    opposite conclusion for an investigator.
    """
    start = to_naive_utc(from_time)
    end = to_naive_utc(to_time)

    if start and end and start > end:
        raise HTTPException(
            status_code=400,
            detail="'from' is later than 'to' - the search window is inverted.",
        )

    return TimeWindow(start=start, end=end)


def apply_window(query, column, window: TimeWindow):
    """Apply a resolved window to a SQLAlchemy query on the given column."""
    if window.start is not None:
        query = query.filter(column >= window.start)
    if window.end is not None:
        query = query.filter(column <= window.end)
    return query
