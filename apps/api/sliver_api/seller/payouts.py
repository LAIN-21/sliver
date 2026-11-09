"""The seller payout schedule (ADR 0005): Sliver pays sellers their net every 15 days.

Rule: payouts run on the 1st and the 16th of each month (UTC) and cover every delivered sale not
yet paid out. Payouts are not automated yet; this module only states when the next one is due.
Pure: no database or clock, so the rule is easy to test.
"""

from datetime import date

PAYOUT_DAYS = (1, 16)
SCHEDULE = "1st and 16th of each month (UTC)"


def next_payout_date(today: date) -> date:
    """The first payout day strictly after `today`."""
    if today.day < PAYOUT_DAYS[1]:
        return today.replace(day=PAYOUT_DAYS[1])
    if today.month == 12:
        return date(today.year + 1, 1, PAYOUT_DAYS[0])
    return date(today.year, today.month + 1, PAYOUT_DAYS[0])
