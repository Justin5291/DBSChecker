"""Bongino Rumble checker for cron-job.org.

Emails only happen when this app returns HTTP 500. cron-job.org must be set
to notify on failure, not on success. A 200 means the expected post exists.

Checks, America/New_York:
- /check/waiting-room  weekday morning: a livestream whose title contains
  today's date, or whose publish time is today
- /check/weekly-report Saturday: a video titled Weekend Report or Weekly Report
  published today

Feeds are OpenRSS copies of the public channel, which Rumble's own pages
block from automated callers.
"""

import os
from datetime import datetime
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import requests
from flask import Flask, request

app = Flask(__name__)

TZ = ZoneInfo(os.environ.get("TIMEZONE", "America/New_York"))
TOKEN = os.environ.get("CHECK_TOKEN", "")
LIVE_FEED = "https://openrss.org/feed/rumble.com/c/bongino/livestreams"
VIDEO_FEED = "https://openrss.org/feed/rumble.com/c/bongino/videos"
HEADERS = {"User-Agent": "bongino-rumble-checker/1.0"}


def authorized():
    return not TOKEN or request.args.get("token") == TOKEN


def load_feed(url):
    response = requests.get(url, timeout=25, headers=HEADERS)
    response.raise_for_status()
    root = ElementTree.fromstring(response.content)
    items = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").replace("VIDEO: ", "").strip()
        link = (item.findtext("link") or "").strip()
        raw = item.findtext("pubDate")
        when = parsedate_to_datetime(raw).astimezone(TZ) if raw else None
        items.append({"title": title, "link": link, "when": when})
    return items


def date_needles(day):
    month, mday, year = day.month, day.day, day.year
    return {
        f"{month}/{mday}/{year}",
        f"{month:02d}/{mday:02d}/{year}",
        f"{month}-{mday}-{year}",
        f"{month:02d}-{mday:02d}-{year}",
    }


def text(lines, status):
    return "\n".join(lines) + "\n", status


@app.get("/")
def health():
    return "bongino checker\n", 200


@app.get("/check/waiting-room")
def waiting_room():
    if not authorized():
        return "bad token\n", 403
    now = datetime.now(TZ)
    if now.weekday() >= 5:
        return text(["OK", "weekend, no weekday waiting room required", now.isoformat()], 200)
    try:
        items = load_feed(LIVE_FEED)
    except (requests.RequestException, ElementTree.ParseError, TypeError, ValueError) as exc:
        return text(["MISSING", "could not read livestream feed", str(exc)], 500)
    needles = date_needles(now.date())
    hits = [
        item for item in items
        if any(needle in item["title"] for needle in needles)
        or (item["when"] is not None and item["when"].date() == now.date())
    ]
    lines = [f"checked {now.strftime('%Y-%m-%d %H:%M %Z')}", f"matches: {len(hits)}"]
    for item in hits[:5]:
        stamp = item["when"].strftime("%Y-%m-%d %H:%M") if item["when"] else "?"
        lines.append(f"- {stamp} {item['title']} {item['link']}")
    if not hits:
        lines.insert(0, "MISSING")
        lines.append("no livestream waiting room or live post for today on rumble.com/c/bongino/livestreams")
        return text(lines, 500)
    lines.insert(0, "OK")
    return text(lines, 200)


@app.get("/check/weekly-report")
def weekly_report():
    if not authorized():
        return "bad token\n", 403
    now = datetime.now(TZ)
    if now.weekday() != 5:
        return text(["OK", "not Saturday, weekly report not required", now.isoformat()], 200)
    try:
        items = load_feed(VIDEO_FEED)
    except (requests.RequestException, ElementTree.ParseError, TypeError, ValueError) as exc:
        return text(["MISSING", "could not read video feed", str(exc)], 500)
    hits = []
    for item in items:
        title = item["title"].lower()
        if "weekend report" not in title and "weekly report" not in title:
            continue
        if item["when"] is not None and item["when"].date() == now.date():
            hits.append(item)
    lines = [f"checked {now.strftime('%Y-%m-%d %H:%M %Z')}", f"matches: {len(hits)}"]
    for item in hits[:5]:
        stamp = item["when"].strftime("%Y-%m-%d %H:%M") if item["when"] else "?"
        lines.append(f"- {stamp} {item['title']} {item['link']}")
    if not hits:
        lines.insert(0, "MISSING")
        lines.append("no Bongino Weekend Report or Weekly Report published today")
        return text(lines, 500)
    lines.insert(0, "OK")
    return text(lines, 200)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
