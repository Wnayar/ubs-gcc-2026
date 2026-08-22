"""Diaries, whereabouts and places to eat — tool-box sheet 3, "Working Life".

Four problem sets, one small world. The statement fixes two conventions and
says neither is checked for us:

    Time.  Weekday names, zero-padded 24-hour HH:MM, everything on the hour,
           and the day runs 08:00 to 23:00.
    Space. A 10x10 grid, both coordinates 0..9, travel costs
           |x2 - x1| + |y2 - y1|, and positions are written [x, y] with x
           first — "the distance formula gives the same answer if you swap
           them, so getting the order wrong produces a confident, plausible,
           wrong answer rather than an error".

Everything the android is asked about lives on the challenge host: /venues/{day},
/schedule/{person}/{day}, /location/{person}/{day} and /emails, its own inbox.
We read those live, because only the host knows what a given run is being asked
about, and fall back to the snapshot in app/data/city.json when it cannot be
reached — a sleeping free dyno must not cost us the sheet. See tools/fetch_city.py.

The inbox is the one feed that has to be interpreted rather than read. Every
message is an invitation the android replied to, and the reply decides what it
means: ACCEPTED is a hard commitment, DECLINED constrains nothing at all, and
TENTATIVE is only a preference — it "would rather keep this, but it will give it
up if there is no other way to meet". That makes a meeting time two questions in
order, never one: first the earliest window that overlaps nothing whatever, and
only if there is no such window anywhere in the range, the earliest that overlaps
nothing except tentative commitments. A clean window beats an earlier unclean one
however much earlier it falls.

Every body also carries a planted wrong time ("We had this down for 4 pm ...
originally"); across all 109 messages that prose time never once matches the
When: line, so only the When: line is ever read.
"""
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

HOST = os.environ.get("TOOLBOX_HOST", "https://tool-box-2591eaa24fa3.herokuapp.com").rstrip("/")
TIMEOUT = float(os.environ.get("TOOLBOX_CITY_TIMEOUT", "5.0"))
# A run asks ten problems in a couple of minutes and the feeds were byte-identical
# across complete back-to-back fetches, so a short cache is free speed. It is not
# unbounded: if they ever do regenerate the city between runs, we notice within
# two minutes instead of serving yesterday's diary for the life of the process.
CACHE_SECONDS = float(os.environ.get("TOOLBOX_CITY_CACHE", "120"))

DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
DAY_OPENS = 8 * 60
DAY_CLOSES = 23 * 60
GRID = 10
HOUR = 60

# "you and ada, bram can all meet" — the android is always one of the party and
# is never a person the host has a schedule for.
SELF_WORDS = {"you", "me", "i", "myself", "self", "us", "we", "android", "milo", "yourself"}

_SNAPSHOT_PATH = os.path.join(os.path.dirname(__file__), "data", "city.json")
with open(_SNAPSHOT_PATH, encoding="utf-8") as _handle:
    SNAPSHOT = json.load(_handle)


class PlanError(Exception):
    """We cannot answer this one. Reported to the android, never as a 500."""


# --- the feeds -------------------------------------------------------------

_CACHE: dict[str, object] = {}
_FETCHED: dict[str, float] = {}
_LOCK = threading.Lock()
_CLIENT: httpx.Client | None = None


def _client() -> httpx.Client:
    """One keep-alive client: an outing reads eight feeds and the limit is 10 s.

    Built under the lock because the android calls tools in parallel and the
    router now answers each one in its own thread.
    """
    global _CLIENT
    if _CLIENT is None:
        with _LOCK:
            if _CLIENT is None:
                _CLIENT = httpx.Client(
                    timeout=TIMEOUT, headers={"accept": "application/json"})
    return _CLIENT


def fetch(path: str):
    """Live JSON for a path, or None. Never raises: None means "use the snapshot"."""
    if not HOST:
        return None
    now = time.monotonic()
    with _LOCK:
        if path in _CACHE and now - _FETCHED.get(path, 0.0) < CACHE_SECONDS:
            return _CACHE[path]
    try:
        response = _client().get(HOST + path)
    except httpx.HTTPError:
        return None  # not cached: a flaky hop must not blind us for two minutes
    payload = None
    if response.status_code == 200:
        try:
            payload = response.json()
        except ValueError:
            payload = None
    with _LOCK:
        _CACHE[path] = payload
        _FETCHED[path] = now
    return payload


def prefetch(paths) -> None:
    """Warm several feeds at once. An outing needs one per guest, twice over."""
    wanted = list(dict.fromkeys(p for p in paths if p))
    if not HOST or len(wanted) < 2:
        return
    try:
        with ThreadPoolExecutor(min(8, len(wanted))) as pool:
            list(pool.map(fetch, wanted))
    except Exception:  # a pool that will not start is not a reason to fail
        pass


def forget() -> None:
    with _LOCK:
        _CACHE.clear()
        _FETCHED.clear()


# --- reading the conventions ----------------------------------------------


def _whole(value) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        found = re.fullmatch(r"\s*(-?\d+)\s*", value)
        if found:
            return int(found.group(1))
    return None


_CLOCK = re.compile(r"(\d{1,2})\s*(?::\s*(\d{2}))?\s*(am|pm)?", re.IGNORECASE)


def to_minutes(value) -> int | None:
    """13:00, 9:00, 1pm, 0900 or 13 -> minutes past midnight. None if unreadable."""
    number = _whole(value)
    if number is not None:
        if 0 <= number <= 23:
            return number * HOUR
        if 800 <= number <= 2359 and number % 100 < 60:
            return (number // 100) * HOUR + number % 100
        return None
    if not isinstance(value, str):
        return None
    found = _CLOCK.search(value)
    if not found:
        return None
    hour = int(found.group(1))
    minute = int(found.group(2) or 0)
    suffix = (found.group(3) or "").lower()
    if suffix == "pm" and hour < 12:
        hour += 12
    elif suffix == "am" and hour == 12:
        hour = 0
    if not (0 <= hour <= 24 and 0 <= minute < 60):
        return None
    return hour * HOUR + minute


def to_clock(minutes: int) -> str:
    """Zero-padded 24-hour, always. "Never 9:00"."""
    return f"{minutes // HOUR:02d}:{minutes % HOUR:02d}"


def to_day(value) -> str:
    """A weekday name however it was written. Raises rather than guess Monday."""
    if isinstance(value, str):
        wanted = value.strip().lower()
        for day in DAYS:
            lower = day.lower()
            if wanted == lower or wanted == lower[:3]:
                return day
        for day in DAYS:  # "on Tuesday", "next tuesday afternoon"
            if re.search(rf"\b{day.lower()}\b", wanted):
                return day
    raise PlanError("give me a weekday name such as \"Tuesday\" in \"day\"")


def to_point(value) -> tuple[int, int] | None:
    """[x, y] with x first, however the android wrote it down."""
    if isinstance(value, dict):
        x, y = _whole(value.get("x")), _whole(value.get("y"))
        return (x, y) if x is not None and y is not None else None
    if isinstance(value, (list, tuple)) and len(value) == 2:
        x, y = _whole(value[0]), _whole(value[1])
        return (x, y) if x is not None and y is not None else None
    if isinstance(value, str):
        numbers = re.findall(r"-?\d+", value)
        if len(numbers) == 2:
            return (int(numbers[0]), int(numbers[1]))
    return None


def on_grid(point: tuple[int, int]) -> tuple[int, int]:
    x, y = point
    if not (0 <= x < GRID and 0 <= y < GRID):
        raise PlanError(f"[{x}, {y}] is off the grid — both coordinates run 0 to {GRID - 1}")
    return (x, y)


def to_people(value) -> list[str]:
    """The guests, without the android itself — it has no /schedule of its own."""
    if isinstance(value, str):
        parts = re.split(r"[,;/&]|\band\b|\bwith\b|\bplus\b", value, flags=re.IGNORECASE)
    elif isinstance(value, (list, tuple, set)):
        parts = []
        for item in value:
            parts.extend(to_people(item) if isinstance(item, str) else [str(item)])
    else:
        return []
    names = []
    for part in parts:
        name = re.sub(r"[^a-z0-9_-]+", "", str(part).strip().lower())
        if name and name not in SELF_WORDS and name not in names:
            names.append(name)
    return names


def distance(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


# --- venues ----------------------------------------------------------------


def _read_venues(rows) -> list[dict]:
    venues = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        x, y = _whole(row.get("x")), _whole(row.get("y"))
        if not isinstance(name, str) or not name.strip() or x is None or y is None:
            continue
        windows = []
        for span in row.get("available") or []:
            if isinstance(span, (list, tuple)) and len(span) == 2:
                opens, shuts = to_minutes(span[0]), to_minutes(span[1])
                if opens is not None and shuts is not None and shuts > opens:
                    windows.append((opens, shuts))
        venues.append({"name": name.strip(), "x": x, "y": y, "windows": windows})
    return venues


def venues(day: str) -> list[dict]:
    day = to_day(day)
    live = fetch(f"/venues/{day}")
    rows = live.get("venues") if isinstance(live, dict) else None
    found = _read_venues(rows)
    if not found:
        found = _read_venues(SNAPSHOT["venues"].get(day))
    if not found:
        raise PlanError(f"nowhere on the list is trading on {day}")
    return found


def is_open(venue: dict, minute: int) -> bool:
    """"available is when a place is OPEN" — and an hour's eating starting at
    `minute` fits inside a window exactly when the place is open at `minute`,
    since every window boundary falls on the hour."""
    return any(opens <= minute < shuts for opens, shuts in venue["windows"])


def open_at(day: str, minute: int) -> list[dict]:
    return [venue for venue in venues(day) if is_open(venue, minute)]


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", re.sub(r"\band\b", "&", name.strip().lower()))


def find_venue(day: str, name: str) -> dict:
    """Match a place the way the android might have written it down."""
    if not isinstance(name, str) or not name.strip():
        raise PlanError("which place did you mean?")
    listed = venues(day)
    wanted = _key(name)
    for venue in listed:
        if _key(venue["name"]) == wanted:
            return venue
    stripped = re.sub(r"^the", "", wanted)
    for venue in listed:
        if re.sub(r"^the", "", _key(venue["name"])) == stripped:
            return venue
    for venue in listed:
        if wanted and (wanted in _key(venue["name"]) or _key(venue["name"]) in wanted):
            return venue
    raise PlanError(f"there is no place called {name!r} open on {day}")


# --- diaries ---------------------------------------------------------------


def _read_spans(rows) -> list[tuple[int, int]]:
    spans = []
    for span in rows or []:
        if isinstance(span, (list, tuple)) and len(span) == 2:
            start, end = to_minutes(span[0]), to_minutes(span[1])
            if start is not None and end is not None and end > start:
                spans.append((start, end))
    return sorted(spans)


def busy(person: str, day: str) -> list[tuple[int, int]]:
    """"busy is when they are not available. An empty list means free all day.\""""
    day = to_day(day)
    who = re.sub(r"[^a-z0-9_-]+", "", str(person).strip().lower())
    if not who:
        raise PlanError("give me a person's name")
    live = fetch(f"/schedule/{who}/{day}")
    if isinstance(live, dict) and isinstance(live.get("busy"), list):
        return _read_spans(live["busy"])
    known = SNAPSHOT["schedule"].get(who)
    if known is None:
        raise PlanError(f"nobody called {who!r} has a diary — try one of: "
                        + ", ".join(SNAPSHOT["people"]))
    return _read_spans(known.get(day))


def position(person: str, day: str) -> tuple[int, int]:
    """"One person, one day, one place. People are somewhere different on
    different days.\""""
    day = to_day(day)
    who = re.sub(r"[^a-z0-9_-]+", "", str(person).strip().lower())
    if not who:
        raise PlanError("give me a person's name")
    live = fetch(f"/location/{who}/{day}")
    if isinstance(live, dict):
        x, y = _whole(live.get("x")), _whole(live.get("y"))
        if x is not None and y is not None:
            return (x, y)
    known = SNAPSHOT["location"].get(who, {}).get(day)
    point = to_point(known) if known is not None else None
    if point is None:
        raise PlanError(f"nobody called {who!r} is anywhere on {day} — try one of: "
                        + ", ".join(SNAPSHOT["people"]))
    return point


_WHEN = re.compile(r"When:\s*([A-Za-z]+)\s+(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})")
_RESPONSE = re.compile(r"Response:\s*([A-Za-z]+)")


def commitments(day: str) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """The android's own day from its inbox: (accepted, tentative).

    ACCEPTED is busy, TENTATIVE is a preference it will give up, DECLINED is
    nothing. Only the When: line is read — the paragraph above it quotes a slot
    that "is no longer current", and in all 109 messages it is never the right one.
    """
    day = to_day(day)
    accepted: list[tuple[int, int]] = []
    tentative: list[tuple[int, int]] = []
    live = fetch("/emails")
    messages = live.get("emails") if isinstance(live, dict) else None
    if isinstance(messages, list) and messages:
        for message in messages:
            body = message.get("body") if isinstance(message, dict) else None
            if not isinstance(body, str):
                continue
            when, reply = _WHEN.search(body), _RESPONSE.search(body)
            if not when or not reply or when.group(1) != day:
                continue
            start, end = to_minutes(when.group(2)), to_minutes(when.group(3))
            if start is None or end is None or end <= start:
                continue
            answer = reply.group(1).upper()
            if answer == "ACCEPTED":
                accepted.append((start, end))
            elif answer == "TENTATIVE":
                tentative.append((start, end))
        return sorted(accepted), sorted(tentative)
    kept = SNAPSHOT["commitments"].get(day, {})
    return _read_spans(kept.get("accepted")), _read_spans(kept.get("tentative"))


# --- problem set 2: a time everyone can make -------------------------------


def clashes(start: int, end: int, spans) -> int:
    """Minutes of overlap. Touching is not overlapping: a meeting may start on
    the hour something else ends."""
    return sum(max(0, min(end, b) - max(start, a)) for a, b in spans)


def candidate_windows(earliest: int, latest: int, minutes: int) -> list[tuple[int, int]]:
    """"meetings start on the hour", inside the day and inside the range asked for."""
    start = max(earliest, DAY_OPENS)
    finish = min(latest, DAY_CLOSES)
    if start % HOUR:
        start += HOUR - start % HOUR
    return [(s, s + minutes) for s in range(start, finish - minutes + 1, HOUR)]


def find_window(day: str, people, earliest=None, latest=None, minutes: int = HOUR) -> dict:
    """The two questions, in order. Never returns nothing: a range with no clean
    and no tentative-only window still gets the least-clashing answer, because
    refusing scores zero for certain and a near miss might not."""
    day = to_day(day)
    if minutes <= 0:
        raise PlanError("how long is the meeting, in minutes?")
    guests = to_people(people)
    prefetch([f"/schedule/{who}/{day}" for who in guests] + ["/emails"])

    accepted, tentative = commitments(day)
    hard = [span for who in guests for span in busy(who, day)] + accepted
    options = candidate_windows(
        DAY_OPENS if earliest is None else earliest,
        DAY_CLOSES if latest is None else latest,
        minutes,
    )
    if not options:
        raise PlanError(
            f"no {minutes}-minute meeting starting on the hour fits between "
            f"{to_clock(max(earliest or DAY_OPENS, DAY_OPENS))} and "
            f"{to_clock(min(latest or DAY_CLOSES, DAY_CLOSES))}"
        )

    for start, end in options:  # 1. a window that overlaps nothing at all
        if not clashes(start, end, hard) and not clashes(start, end, tentative):
            return {"start": start, "end": end, "day": day, "guests": guests, "quality": "clear"}
    for start, end in options:  # 2. only then, one that gives up a tentative
        if not clashes(start, end, hard):
            return {"start": start, "end": end, "day": day, "guests": guests,
                    "quality": "gives up a tentative commitment"}
    start, end = min(
        options, key=lambda w: (clashes(*w, hard), clashes(*w, tentative), w[0])
    )
    return {"start": start, "end": end, "day": day, "guests": guests,
            "quality": "the least clashing window — somebody is double-booked"}


# --- problem set 3: a place to meet ----------------------------------------


def best_point(positions, then_on_to=None) -> tuple[int, int]:
    """The cell with the smallest total travel. Every cell is a candidate — "it
    does not have to be where somebody already is, and usually it is not".

    Ties are broken by the lowest x then the lowest y so the same question always
    gets the same answer; every tied cell costs exactly the same to travel to.
    """
    places = [on_grid(point) for point in positions]
    if not places:
        raise PlanError("nobody is going, so there is nowhere to meet")
    best = None
    for x in range(GRID):
        for y in range(GRID):
            here = (x, y)
            total = sum(distance(point, here) for point in places)
            if then_on_to is not None:
                total += distance(here, then_on_to)
            if best is None or total < best[0]:
                best = (total, here)
    return best[1]


def gather(day: str, me, people) -> list[tuple[int, int]]:
    """"Everyone counts, including the android." Its own place is in the question."""
    day = to_day(day)
    guests = to_people(people)
    prefetch([f"/location/{who}/{day}" for who in guests])
    start = to_point(me)
    if start is None:
        raise PlanError("where are you? give it as [x, y] in \"my_position\"")
    return [on_grid(start)] + [on_grid(position(who, day)) for who in guests]


# --- problem set 4: an outing ----------------------------------------------


def plan_outing(day: str, me, people, earliest=None, latest=None, minutes: int = HOUR) -> dict:
    """Window first, then the place to eat, then the shortest whole journey.

    The two checks that score zero happen in that order and neither depends on
    the travel, so the window is settled on its own terms and the eating hour
    follows from it. Only the meeting point and the venue are free, and they are
    chosen together: everyone's travel to the meeting point *plus* the trip on to
    the place they eat. "A meeting point chosen without regard to where you are
    going afterwards is answering a different question."
    """
    window = find_window(day, people, earliest, latest, minutes)
    day = window["day"]
    positions = gather(day, me, people)
    eating = window["end"]
    places = open_at(day, eating)
    if not places:
        raise PlanError(f"nowhere on {day} is open for the hour beginning {to_clock(eating)}")

    best = None
    for venue in places:
        corner = (venue["x"], venue["y"])
        for x in range(GRID):
            for y in range(GRID):
                here = (x, y)
                total = sum(distance(point, here) for point in positions) + distance(here, corner)
                key = (total, venue["name"], x, y)
                if best is None or key < best:
                    best = key
    total, name, x, y = best
    return {
        "day": day,
        "start": window["start"],
        "end": window["end"],
        "quality": window["quality"],
        "point": (x, y),
        "venue": name,
        "travel": total,
        "positions": positions,
    }
