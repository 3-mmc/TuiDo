"""Days and lengths of time as you'd say them: 'fri', 'tomorrow', '3 nov', '+3d', 'next week' for
a task's due day; '25', '25m', '1h30' for a timer."""
import re
from datetime import date, timedelta

MONTHS = ('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec')
FULL = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')
SAYS = 'fri  tomorrow  3 nov  +3d  next week'


def day(text, today):
    """The day `text` names: on or after `today`, or a date this year gone within six months (late);
    None if it names none."""
    t = ' '.join(text.lower().replace(',', ' ').split())
    if t in ('today', 'tod'):
        return today
    if t in ('tomorrow', 'tmrw'):
        return today + timedelta(days=1)
    if t == 'next week':
        return today + timedelta(days=7 - today.weekday())
    m = re.fullmatch(r'\+?(\d+)\s*(d|days?|w|weeks?)', t)
    if m:
        return today + timedelta(days=int(m[1]) * (7 if m[2][0] == 'w' else 1))
    wd = next((i for i, full in enumerate(FULL) if len(t) >= 3 and full.startswith(t)), None)
    if wd is not None:
        return today + timedelta(days=(wd - today.weekday()) % 7)
    m = re.fullmatch(r'(\d{4})-(\d\d)-(\d\d)', t)
    try:
        if m:
            return date(int(m[1]), int(m[2]), int(m[3]))
        m = re.fullmatch(r'(\d{1,2}) ([a-z]{3})[a-z]*|([a-z]{3})[a-z]* (\d{1,2})', t)
        if not m or (m[2] or m[3]) not in MONTHS:
            return None
        got = date(today.year, MONTHS.index(m[2] or m[3]) + 1, int(m[1] or m[4]))
    except ValueError:
        return None
    # gone this year: next year's, unless it's lately gone (a due day that's late, said again)
    return got if got >= today - timedelta(days=183) else got.replace(year=got.year + 1)


def minutes(text):
    """How many minutes `text` says ('25', '25m', '1h', '1h30', '90 min'); None if it says none."""
    t = text.lower().replace(' ', '')
    m = re.fullmatch(r'(?:(\d+)h)?(?:(\d+)(?:m|min|mins)?)?', t)
    if not t or not m or not (m[1] or m[2]):
        return None
    got = int(m[1] or 0) * 60 + int(m[2] or 0)
    return got or None


def due_text(due, today):
    """'today', 'tomorrow', 'fri' (this week), '3 Nov'; '2 days late' once it's gone."""
    days = (due - today).days
    if days < 0:
        return 'a day late' if days == -1 else f'{-days} days late'
    if days == 0:
        return 'due today'
    if days == 1:
        return 'due tomorrow'
    return f'due {due:%a}' if days < 7 else f'due {due.day} {due:%b}'
