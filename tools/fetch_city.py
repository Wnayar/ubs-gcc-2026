"""Snapshot the tool-box sheet-3 city data into app/data/city.json.

Sheet 3's four problem sets all read the same five feeds on the challenge host:
venues, a friend's schedule, a friend's whereabouts, and the android's own
inbox. `app/cityclock.py` reads them live, because a run's questions are only
answerable from whatever the host is serving that day — but a free Heroku dyno
that is asleep, slow or down would otherwise cost us every point on the sheet.

So we keep a snapshot to fall back to. Fetched 2026-08-22 and byte-identical
across two complete back-to-back fetches, which is the same evidence that let
sheet 2 vendor its corpus. Re-run this after any change on their side:

    python3 tools/fetch_city.py

The inbox is stored already parsed — sheet 3 only ever needs each invitation's
day, hour and reply, and the prose in the body is a deliberate trap (see
notes.md: the "originally at 4 pm" line never matches the When: line).
"""
import json
import os
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HOST = os.environ.get("TOOLBOX_HOST", "https://tool-box-2591eaa24fa3.herokuapp.com").rstrip("/")
OUT = os.path.join(os.path.dirname(__file__), "..", "app", "data", "city.json")

DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
# a..j, one name each; probed by asking /schedule for every short name we could
# think of and keeping the ones that answered 200. `juno` was missed on the
# first sweep and turned up in three questions of the first graded run — the
# live feeds answered for it, but the offline fallback had a hole where it sat.
PEOPLE = ("ada", "bram", "cira", "dov", "esme", "fenn", "gita", "hale", "iris", "juno")

WHEN = re.compile(r"When:\s*([A-Za-z]+)\s+(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})")
RESPONSE = re.compile(r"Response:\s*([A-Za-z]+)")


def get(path: str):
    with urllib.request.urlopen(HOST + path, timeout=30) as response:
        return path, json.load(response)


def main() -> int:
    paths = ["/emails"]
    paths += [f"/venues/{day}" for day in DAYS]
    paths += [f"/schedule/{who}/{day}" for who in PEOPLE for day in DAYS]
    paths += [f"/location/{who}/{day}" for who in PEOPLE for day in DAYS]
    with ThreadPoolExecutor(8) as pool:
        raw = dict(pool.map(get, paths))

    commitments = {day: {"accepted": [], "tentative": []} for day in DAYS}
    for message in raw["/emails"]["emails"]:
        body = message.get("body", "")
        when, reply = WHEN.search(body), RESPONSE.search(body)
        if not when or not reply:
            continue
        day, answer = when.group(1), reply.group(1).upper()
        if day not in commitments or answer not in ("ACCEPTED", "TENTATIVE"):
            continue  # DECLINED constrains nothing at all
        commitments[day]["accepted" if answer == "ACCEPTED" else "tentative"].append(
            [when.group(2), when.group(3)]
        )
    for day in DAYS:
        for kind in ("accepted", "tentative"):
            commitments[day][kind].sort()

    snapshot = {
        "host": HOST,
        "days": list(DAYS),
        "people": list(PEOPLE),
        "venues": {day: raw[f"/venues/{day}"]["venues"] for day in DAYS},
        "schedule": {
            who: {day: raw[f"/schedule/{who}/{day}"]["busy"] for day in DAYS}
            for who in PEOPLE
        },
        "location": {
            who: {
                day: [raw[f"/location/{who}/{day}"]["x"], raw[f"/location/{who}/{day}"]["y"]]
                for day in DAYS
            }
            for who in PEOPLE
        },
        "commitments": commitments,
        "emails": len(raw["/emails"]["emails"]),
    }
    with open(os.path.abspath(OUT), "w", encoding="utf-8") as handle:
        json.dump(snapshot, handle, ensure_ascii=False, indent=1, sort_keys=True)
        handle.write("\n")
    print(f"wrote {os.path.abspath(OUT)} from {snapshot['emails']} emails")
    return 0


if __name__ == "__main__":
    sys.exit(main())
