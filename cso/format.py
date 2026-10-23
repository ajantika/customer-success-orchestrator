"""Human-readable formatting shared by the UI and customer-facing messages."""
from __future__ import annotations

from datetime import datetime

STATUS_LABEL = {
    "open": "Open", "assigned": "Assigned", "in_progress": "In progress", "resolved": "Resolved", "closed": "Closed",
    "generated": "Generated", "reviewed": "Reviewed", "accepted": "Accepted", "edited": "Edited", "dismissed": "Dismissed",
    "deferred": "Deferred", "discussed": "Discussed", "withdrawn": "Withdrawn", "scheduled": "Scheduled", "cancelled": "Cancelled",
    "completed": "Completed", "pending": "Pending", "executed": "Done",
}


def status(s: str | None) -> str:
    return STATUS_LABEL.get(s or "", (s or "").replace("_", " ").capitalize())


def when(iso: str | datetime | None, with_time: bool = True) -> str:
    """'2026-10-26T09:00:00' -> 'Oct 26 at 9 AM'."""
    if not iso:
        return "not set"
    dt = iso if isinstance(iso, datetime) else datetime.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S")
    day = f"{dt:%b} {dt.day}"
    if not with_time:
        return day
    hour = dt.strftime("%I").lstrip("0") or "12"
    mins = f":{dt:%M}" if dt.minute else ""
    return f"{day} at {hour}{mins} {dt:%p}"
