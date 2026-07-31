# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Statutory compliance calendar engine.

Pure, stateless date-math for the "Compliance" recurring-task feature.
Unlike ``plane.utils.recurrence`` (a fixed date-stepping cursor), a
compliance template's due date depends on its cadence: monthly tasks report
the *previous* month, quarterly tasks only fire in the month after a quarter
closes, annual tasks fire once a year in a fixed month, and advance-tax
tasks fire on a fixed quarterly-but-different schedule.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional

from plane.utils.recurrence import _clamp_day

MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def previous_month(as_of: date) -> dict:
    """Return the previous calendar month relative to ``as_of``.

    e.g. as_of = 2026-08-23 -> {"year": 2026, "month": 7, "label": "July 2026"}.
    """
    year, month = (as_of.year, as_of.month - 1) if as_of.month > 1 else (as_of.year - 1, 12)
    return {"year": year, "month": month, "label": f"{MONTHS[month - 1]} {year}"}


def _closed_quarter_label(as_of: date) -> str:
    """Label of the calendar quarter that just closed, for the months
    quarterly tasks are due in (Apr/Jul/Oct/Jan)."""
    mapping = {
        4: ("Q4", as_of.year - 1),  # Jan-Mar closed, filed in Apr (FY label)
        7: ("Q1", as_of.year),
        10: ("Q2", as_of.year),
        1: ("Q3", as_of.year - 1),
    }
    quarter, year = mapping[as_of.month]
    return f"{quarter} {year}"


def format_task_name(name_template: str, title: str, period_label: str) -> str:
    """Render a template's name pattern. Placeholders: {title} {period} {month} {year}.

    Falls back to a fixed ``"{title} - {period}"`` shape if the pattern is
    malformed — this should be unreachable in practice since
    ``ComplianceTemplateSerializer.validate_name_template`` rejects bad
    patterns at edit time, but a background task must never raise on
    user-authored input.
    """
    parts = (period_label or "").split()
    month = parts[0] if parts else ""
    year = parts[-1] if parts else ""
    try:
        return name_template.format(title=title, period=period_label, month=month, year=year)
    except (KeyError, IndexError, ValueError):
        return f"{title} - {period_label}"


@dataclass(frozen=True)
class GeneratedTask:
    period_label: str
    # The statutory due date computed from the template's due_day/due_month.
    # Assigned as the generated Issue's *start_date*, not its target_date —
    # the task is only created on this date (see the day-gate below), so
    # there is no separate "deadline still ahead" to track via target_date.
    due_date: date
    title: str


def generate_due_task(template, as_of: date) -> Optional[GeneratedTask]:
    """Compute the due task for a single ``ComplianceTemplate`` on ``as_of``,
    or ``None`` if this cadence isn't due to fire on this exact date.

    The task is created on its due date, not at the start of the period —
    each cadence branch below only establishes which month(s) are eligible;
    the final day-gate is what actually restricts firing to due_day itself.
    """
    cadence = template.cadence

    if cadence == "monthly":
        period_label = previous_month(as_of)["label"]
    elif cadence == "quarterly":
        if as_of.month not in (4, 7, 10, 1):
            return None
        period_label = _closed_quarter_label(as_of)
    elif cadence == "annual":
        if as_of.month != (template.due_month or 0):
            return None
        period_label = f"FY {as_of.year - 1}-{str(as_of.year)[2:]}"
    elif cadence == "advance_tax":
        if as_of.month not in (6, 9, 12, 3):
            return None
        period_label = f"{MONTHS[as_of.month - 1]} {as_of.year}"
    else:
        return None

    due_date = date(as_of.year, as_of.month, _clamp_day(as_of.year, as_of.month, template.due_day))
    if as_of != due_date:
        return None

    title = format_task_name(template.name_template, template.title, period_label)
    return GeneratedTask(period_label=period_label, due_date=due_date, title=title)
