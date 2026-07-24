# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import calendar
from datetime import date

# Third party imports
from dateutil.relativedelta import relativedelta


def derive_days_of_month(start_day, times):
    """Spread ``times`` occurrences across a month, anchored at ``start_day``.

    e.g. start_day=23, times=2 -> [8, 23]. The start day is always kept; the
    others are spaced ~evenly and wrapped into the 1..30 range.
    """
    if times <= 1:
        return [start_day]
    step = max(1, round(30 / times))
    days = {start_day}
    for i in range(1, times):
        days.add(((start_day - 1 + i * step) % 30) + 1)
    return sorted(days)


def _clamp_day(year, month, day):
    """Clamp ``day`` to the last valid day of the given month."""
    last = calendar.monthrange(year, month)[1]
    return min(day, last)


def next_month_day(after_date, days_of_month):
    """Return the earliest date strictly after ``after_date`` whose day is in
    ``days_of_month``, clamped to each month's length. Scans up to 24 months.
    """
    if not days_of_month:
        return None
    days = sorted(days_of_month)
    year, month = after_date.year, after_date.month
    for _ in range(24):
        for day in days:
            candidate = date(year, month, _clamp_day(year, month, day))
            if candidate > after_date:
                return candidate
        month += 1
        if month > 12:
            month = 1
            year += 1
    return None


def add_interval(base_date, frequency, interval=1):
    """Advance ``base_date`` by ``interval`` units of ``frequency``.

    Supported frequencies: ``daily``, ``weekly``, ``monthly``. Returns a new
    ``date``; the input is not mutated.
    """
    if base_date is None:
        return None

    if frequency == "daily":
        return base_date + relativedelta(days=interval)
    if frequency == "weekly":
        return base_date + relativedelta(weeks=interval)
    if frequency == "monthly":
        return base_date + relativedelta(months=interval)

    raise ValueError(f"Unsupported recurrence frequency: {frequency}")
