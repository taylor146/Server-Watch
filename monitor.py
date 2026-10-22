#!/usr/bin/env python3
"""
Server Watch — pings Slack when the online services for 1v1Me's seven
leagues have problems, and when planned maintenance is announced.

Runs once per invocation (GitHub Actions calls it every ~5 minutes).
Standard library only — no pip install needed.

Usage:
    python monitor.py               # normal run (posts to Slack)
    python monitor.py --dry-run     # print alerts instead of posting
    python monitor.py --test-slack  # send one test message and exit
    python monitor.py --status      # print the current state of every source
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import config

PT = ZoneInfo("America/Los_Angeles")
STATE_FILE = os.environ.get("STATE_FILE", os.path.join(os.path.dirname(__file__), "state.json"))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")


# ════════════════════════════════════════════════════════════════════════
# Data shapes
# ════════════════════════════════════════════════════════════════════════
@dataclass
class Issue:
    """Something that is wrong right now. Tracked until it disappears."""
    key: str
    game: str
    title: str
    detail: str = ""
    url: str = ""
    kind: str = "outage"          # outage | degraded | maintenance
    loud: bool = True             # @-mention the channel?
    fingerprint: str = ""         # changes -> "update" post

    def fp(self) -> str:
        return self.fingerprint or hashlib.sha1(f"{self.title}|{self.detail}".encode()).hexdigest()[:12]


@dataclass
class Announcement:
    """A one-off post (maintenance notice, outage notice). Posted once."""
    key: str
    game: str
    title: str
    text: str = ""
    url: str = ""
    kind: str = "maintenance"     # maintenance | outage | info
    start: datetime | None = None
    end: datetime | None = None
    posted_at: datetime | None = None


@dataclass
class SourceResult:
    issues: list[Issue] = field(default_factory=list)
    announcements: list[Announcement] = field(default_factory=list)
    summary: str = ""             # for --status


# ════════════════════════════════════════════════════════════════════════
# HTTP
# ════════════════════════════════════════════════════════════════════════
def http(url: str, *, data: dict | None = None, headers: dict | None = None,
         timeout: int = 20) -> str:
    h = {"User-Agent": UA, "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
         "Accept-Language": "en-US,en;q=0.9"}
    h.update(headers or {})
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def http_json(url: str, **kw):
    return json.loads(http(url, **kw))


# ════════════════════════════════════════════════════════════════════════
# Text helpers
# ════════════════════════════════════════════════════════════════════════
def strip_html(s: str) -> str:
    s = re.sub(r"<br\s*/?>|</p>|</li>|</h\d>", "\n", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t\r]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n", s)
    return s.strip()


def has_any(text: str, words: list[str]) -> bool:
    t = (text or "").lower()
    return any(w in t for w in words)


def clip(s: str, n: int = 400) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], 1)}


def _to_24h(hm: str, ap: str) -> tuple[int, int]:
    h, m = (int(x) for x in hm.split(":"))
    ap = ap.lower()
    if ap == "p" and h != 12:
        h += 12
    if ap == "a" and h == 12:
        h = 0
    return h, m


def _year_for(month: int, ref: datetime) -> int:
    # Notices omit the year. Use the post date; roll over at New Year.
    y = ref.year
    if month < ref.month - 6:
        y += 1
    elif month > ref.month + 6:
        y -= 1
    return y


# "Monday, October 12, 7:00 p.m. – 12:00 a.m. PDT"           (Capcom)
RX_CAPCOM = re.compile(
    r"(?:\w+day,\s*)?(?P<mon>[A-Z][a-z]+)\s+(?P<day>\d{1,2}),?\s+"
    r"(?P<sh>\d{1,2}:\d{2})\s*(?P<sap>[ap])\.?\s*m\.?\s*[–\-~to]+\s*"
    r"(?:(?:\w+day,\s*)?(?P<emon>[A-Z][a-z]+)\s+(?P<eday>\d{1,2}),?\s+)?"
    r"(?P<eh>\d{1,2}:\d{2})\s*(?P<eap>[ap])\.?\s*m\.?\s*(?P<tz>PDT|PST|PT)",
    re.I)
# "[PDT] Wednesday, September 9th, 6:30 PM – 9:00 PM"         (Bandai Namco)
RX_BANDAI = re.compile(
    r"\[(?P<tz>PDT|PST|PT)\]\s*(?:\w+day,\s*)?(?P<mon>[A-Z][a-z]+)\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?,?\s+"
    r"(?P<sh>\d{1,2}:\d{2})\s*(?P<sap>[ap])\.?\s*m\.?\s*[–\-~]+\s*"
    r"(?:(?:\w+day,\s*)?(?P<emon>[A-Z][a-z]+)\s+(?P<eday>\d{1,2})(?:st|nd|rd|th)?,?\s+)?"
    r"(?P<eh>\d{1,2}:\d{2})\s*(?P<eap>[ap])\.?\s*m\.?",
    re.I)


def parse_pacific_window(text: str, ref: datetime) -> tuple[datetime | None, datetime | None, str]:
    """Find a Pacific-time maintenance window in free text.
    Returns (start, end, matched_text). Year inferred from `ref`."""
    for rx in (RX_BANDAI, RX_CAPCOM):
        m = rx.search(text or "")
        if not m:
            continue
        mon = MONTHS.get(m["mon"].lower())
        if not mon:
            continue
        try:
            ref_pt = ref.astimezone(PT)
            y = _year_for(mon, ref_pt)
            sh, sm = _to_24h(m["sh"], m["sap"])
            start = datetime(y, mon, int(m["day"]), sh, sm, tzinfo=PT)
            eh, em = _to_24h(m["eh"], m["eap"])
            if m["emon"] and MONTHS.get(m["emon"].lower()):
                emon = MONTHS[m["emon"].lower()]
                end = datetime(_year_for(emon, ref_pt), emon, int(m["eday"]), eh, em, tzinfo=PT)
            else:
                end = start.replace(hour=eh, minute=em)
                if end <= start:            # crosses midnight ("7pm – 12am")
                    end += timedelta(days=1)
            return start, end, m.group(0)
        except ValueError:
            continue
    return None, None, ""


def iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


# ════════════════════════════════════════════════════════════════════════
# Sources
# ════════════════════════════════════════════════════════════════════════
def src_ea() -> SourceResult:
    """EA server status feed — Madden + FC."""
    url = "https://help.ea.com/_data/server-status/v1/server-statuses"
    page = "https://help.ea.com/en/server-status/"
    data = http_json(url)["response"]
    res = SourceResult()
    parts = []
    for slug, name in config.EA_GAMES.items():
        st = data.get(slug)
        parts.append(f"{name}: {st or 'not listed'}")
        if st is None or st.strip().lower() == "online":
            continue
        low = st.lower()
        kind = "maintenance" if "mainten" in low else ("degraded" if "some" in low or "degrad" in low else "outage")
        res.issues.append(Issue(
            key=f"ea:{slug}", game=name, title=f"EA reports: {st}",
            url=page, kind=kind, fingerprint=st,
        ))
    res.summary = "; ".join(parts)

    # Banner alerts EA shows on the status page (often maintenance notices)
    try:
        alerts = http_json("https://help.ea.com/_data/playershell/v1/alerts/en?path=/server-status/")["response"]
        for a in alerts or []:
            blob = json.dumps(a, ensure_ascii=False)
            text = strip_html(" ".join(str(v) for v in _walk_strings(a)))
            if not has_any(text, ["madden", "fc", "fifa", "ea app", "ea sports", "maintenance", "outage"]):
                continue
            k = "ea-alert:" + hashlib.sha1(blob.encode()).hexdigest()[:16]
            start, end, _ = parse_pacific_window(text, datetime.now(timezone.utc))
            res.announcements.append(Announcement(
                key=k, game="EA (Madden / FC)", title="EA Help banner alert",
                text=clip(text, 500), url=page,
                kind="maintenance" if has_any(text, config.MAINTENANCE_WORDS) else "outage",
                start=start, end=end))
    except Exception:
        pass  # banner is a bonus; status feed above is what matters
    return res


def _walk_strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from _walk_strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk_strings(v)


def cod_only_ignored_modes(text: str) -> bool:
    """True when CoD text is only about Warzone/DMZ (not Multiplayer)."""
    t = f" {(text or '').lower()} "
    if not any(m in t for m in config.COD_IGNORE_MODES):
        return False
    return not any(k in t for k in config.COD_KEEP_WORDS)


def src_activision() -> SourceResult:
    """Activision Online Services feed — Call of Duty."""
    url = "https://prod-psapi.infra-ext.activision.com/open/api/apexrest/oshp/landingpage"
    data = http_json(url, headers={"Origin": "https://support.activision.com",
                                   "Referer": "https://support.activision.com/onlineservices"})
    res = SourceResult()
    watched = [t.lower() for t in config.COD_TITLES]
    for it in data.get("issuesListRO") or []:
        game = it.get("OSHP_Game_Title__c") or ""
        name = it.get("Name") or ""
        if "test alert" in name.lower():
            continue
        if not any(w in game.lower() for w in watched):
            continue
        subject = it.get("OSHP_Event_Subject__c") or name
        desc = strip_html(it.get("OSHP_Event_Description__c") or "")
        platforms = (it.get("OSHP_Platform__c") or "").replace(";", ", ")
        blob = f"{name} {subject} {desc}"
        if cod_only_ignored_modes(blob):
            continue
        kind = "maintenance" if "mainten" in blob.lower() else "outage"
        event_id = it.get("OSHP_Event_ID__c") or it.get("Id")
        res.issues.append(Issue(
            key=f"atvi:{it.get('Id')}",
            game=game.replace(";", " / "),
            title=subject,
            detail=f"{clip(desc, 350)}\nPlatforms: {platforms or 'n/a'}",
            url=f"https://support.activision.com/onlineservices/event-details?event={event_id}",
            kind=kind,
            fingerprint=it.get("LastModifiedDate") or "",
        ))
    res.summary = f"{len(res.issues)} open CoD incident(s) (feed updated {data.get('updatedTime')})"
    return res


def src_statuspage(base: str, game: str, priority: list[str]) -> SourceResult:
    """Any Atlassian Statuspage (NBA 2K uses one)."""
    data = http_json(base.rstrip("/") + "/api/v2/summary.json")
    res = SourceResult()
    groups = {c["id"]: c["name"] for c in data.get("components", []) if c.get("group")}
    bad = []
    for c in data.get("components", []):
        if c.get("group"):
            continue
        st = c.get("status", "operational")
        if st == "operational":
            continue
        grp = groups.get(c.get("group_id"), "")
        label = c["name"] + (f" ({grp})" if grp else "")
        bad.append(f"{label}: {st.replace('_', ' ')}")
        kind = {"under_maintenance": "maintenance", "degraded_performance": "degraded"}.get(st, "outage")
        res.issues.append(Issue(
            key=f"sp:{base}:comp:{c['id']}", game=game,
            title=f"{label} — {st.replace('_', ' ')}",
            url=base, kind=kind, fingerprint=st,
            loud=any(p.lower() == c["name"].lower() for p in priority) and kind != "maintenance",
        ))
    for inc in data.get("incidents", []):
        upd = (inc.get("incident_updates") or [{}])[0]
        res.issues.append(Issue(
            key=f"sp:{base}:inc:{inc['id']}", game=game,
            title=f"Incident: {inc.get('name')} ({inc.get('impact', 'n/a')} impact)",
            detail=f"*{upd.get('status', inc.get('status', '')).title()}:* {clip(strip_html(upd.get('body', '')), 400)}",
            url=inc.get("shortlink") or base, kind="outage",
            fingerprint=upd.get("id") or inc.get("status", ""),
        ))
    for mt in data.get("scheduled_maintenances", []):
        start, end = iso(mt.get("scheduled_for")), iso(mt.get("scheduled_until"))
        upd = (mt.get("incident_updates") or [{}])[0]
        res.announcements.append(Announcement(
            key=f"sp:{base}:mt:{mt['id']}", game=game,
            title=f"Scheduled maintenance: {mt.get('name')}",
            text=clip(strip_html(upd.get("body", "")), 400),
            url=mt.get("shortlink") or base, kind="maintenance", start=start, end=end))
        if mt.get("status") == "in_progress":
            res.issues.append(Issue(
                key=f"sp:{base}:mtlive:{mt['id']}", game=game,
                title=f"Maintenance in progress: {mt.get('name')}",
                url=mt.get("shortlink") or base, kind="maintenance", loud=False,
                fingerprint="in_progress"))
    ind = data.get("status", {}).get("description", "?")
    res.summary = ind + (f" — {'; '.join(bad)}" if bad else "")
    return res


def src_cs2() -> SourceResult:
    """Valve's official CS2 game-coordinator status (needs STEAM_API_KEY)."""
    key = os.environ.get("STEAM_API_KEY", "").strip()
    if not key:
        raise SkipSource("STEAM_API_KEY not set")
    r = http_json(f"https://api.steampowered.com/ICSGOServers_730/GetGameServersStatus/v1/?key={key}")["result"]
    res = SourceResult()
    page = "https://steamstat.us/"
    bad = []
    labels = {"SessionsLogon": "Steam / CS2 login"}
    ignored = []
    for svc, st in (r.get("services") or {}).items():
        if str(st).lower() in ("normal", "idle"):
            continue
        if svc not in config.CS2_SERVICES_WATCH:
            ignored.append(f"{svc}={st}")
            continue
        bad.append((f"cs2:svc:{svc}", f"{labels.get(svc, svc)}: {st}", True))
    mm = r.get("matchmaking") or {}
    # "surge" just means busy; only "delayed"/"offline" (or anything unknown) can stop a match.
    if config.CS2_WATCH_MATCHMAKING and str(mm.get("scheduler", "normal")).lower() not in ("normal", "surge"):
        bad.append(("cs2:mm", f"Game coordinator / matchmaking: {mm.get('scheduler')}", True))
    for dc, info in (r.get("datacenters") or {}).items():
        if not any(dc.startswith(p) for p in config.CS2_DATACENTER_PREFIXES):
            continue
        vals = {str(v).lower() for v in (info or {}).values()}
        if vals & {"offline", "down"}:
            bad.append((f"cs2:dc:{dc}", f"{dc} servers offline ({', '.join(f'{k}: {v}' for k, v in info.items())})", True))
    for k, title, loud in bad:
        res.issues.append(Issue(key=k, game="CS2", title=title, url=page, loud=loud,
                                kind="degraded" if "delayed" in title.lower() else "outage",
                                fingerprint=title))
    res.summary = (f"scheduler={mm.get('scheduler')}, players={mm.get('online_players', '?')}, "
                   f"searching={mm.get('searching_players', '?')}, avg wait={mm.get('search_seconds_avg', '?')}s"
                   + (f" — {len(bad)} problem(s)" if bad else "")
                   + (f" (ignored: {', '.join(ignored)})" if ignored else ""))
    return res


def src_sf6() -> SourceResult:
    """Capcom's Buckler's Boot Camp 'Administrative Info' (maintenance + outage notices)."""
    page = "https://www.streetfighter.com/6/buckler/information/all/1"
    raw = http(page, headers={"Accept": "text/html"})
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', raw, re.S)
    if not m:
        raise RuntimeError("SF6 page layout changed (no __NEXT_DATA__)")
    items = json.loads(m.group(1))["props"]["pageProps"]["info_list"]
    res = SourceResult()
    for it in items:
        title = it.get("title", "")
        cat = f"{it.get('category', '')} {it.get('categorySlug', '')}".lower()
        body = strip_html(it.get("body", ""))
        is_outage = "outage" in cat or "trouble" in cat or "failure" in cat or has_any(title, ["outage", "issue", "problem"])
        is_maint = "maintenance" in title.lower() or "mainte" in (it.get("slug") or "")
        if not (is_outage or is_maint):
            continue  # skip "Update Notice", battle changes, site updates
        posted = datetime.fromtimestamp(it.get("releaseDate") or time.time(), tz=timezone.utc)
        start, end, _ = parse_pacific_window(body, posted)
        res.announcements.append(Announcement(
            key=f"sf6:{it.get('slug')}", game="Street Fighter 6",
            title=title, text=clip(body, 450),
            url=f"https://www.streetfighter.com/6/buckler/information/detail/{it.get('slug')}",
            kind="outage" if is_outage and not is_maint else "maintenance",
            start=start, end=end, posted_at=posted))
    res.summary = f"latest notice: {items[0].get('title') if items else 'none'}"
    return res


TEKKEN_HYGRAPH = "https://us-east-1-bandai.cdn.hygraph.com/content/clhzxhvgm2yir01uh8dv71asq/master"


def src_tekken() -> SourceResult:
    """Bandai Namco's TEKKEN 8 news CMS — patch notes include the maintenance window."""
    q = """{ articles(stage: PUBLISHED, locales: [en], orderBy: date_DESC, first: 10,
             where: {games_some: {slug: "tekken-8"}}) {
             id title slug date external_url content { content } } }"""
    data = http_json(TEKKEN_HYGRAPH, data={"query": q})
    if data.get("errors"):
        raise RuntimeError(data["errors"][0].get("message"))
    res = SourceResult()
    arts = data["data"]["articles"]
    for a in arts:
        body = strip_html((a.get("content") or {}).get("content") or "")
        title = a.get("title", "")
        if not (has_any(title, ["maintenance", "server", "outage"]) or "maintenance schedule" in body.lower()
                or has_any(body[:600], ["emergency maintenance", "server maintenance"])):
            continue
        posted = iso(a.get("date")) or datetime.now(timezone.utc)
        start, end, line = parse_pacific_window(body, posted)
        i = body.lower().find("maintenance schedule")
        snippet = body[i:i + 300] if i >= 0 else body[:300]
        res.announcements.append(Announcement(
            key=f"tekken:{a['id']}", game="TEKKEN 8", title=title, text=clip(snippet, 350),
            url=a.get("external_url") or f"https://www.bandainamcoent.com/news/{a.get('slug')}",
            kind="maintenance", start=start, end=end, posted_at=posted))
    res.summary = f"latest article: {arts[0]['title'] if arts else 'none'}"
    return res


def src_steam_news() -> SourceResult:
    """Steam news posts for CS2 / SF6 / TEKKEN 8 that mention maintenance or outages."""
    res = SourceResult()
    for appid, game in config.STEAM_NEWS_APPS.items():
        d = http_json(f"https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
                      f"?appid={appid}&count=10&maxlength=0&format=json")
        for n in d.get("appnews", {}).get("newsitems", []):
            title = n.get("title", "")
            body = strip_html(re.sub(r"\[/?[a-z0-9*=_ ]+\]", " ", n.get("contents", ""), flags=re.I))
            text = f"{title}\n{body}"
            maint = has_any(text, config.MAINTENANCE_WORDS)
            outage = has_any(text, config.OUTAGE_WORDS)
            if not (maint or outage):
                continue
            posted = datetime.fromtimestamp(n.get("date", time.time()), tz=timezone.utc)
            start, end, _ = parse_pacific_window(body, posted)
            i = max(body.lower().find("maintenance"), 0)
            res.announcements.append(Announcement(
                key=f"steam:{appid}:{n.get('gid')}", game=game, title=title,
                text=clip(body[max(i - 80, 0): i + 320], 380), url=n.get("url", ""),
                kind="maintenance" if maint else "outage", start=start, end=end, posted_at=posted))
    res.summary = f"{len(res.announcements)} maintenance/outage post(s) in recent Steam news"
    return res


def src_x() -> SourceResult:
    """Optional: official X accounts (needs paid X API; set X_BEARER_TOKEN)."""
    tok = os.environ.get("X_BEARER_TOKEN", "").strip()
    if not tok:
        raise SkipSource("X_BEARER_TOKEN not set")
    froms = " OR ".join(f"from:{u}" for u in config.X_ACCOUNTS)
    words = " OR ".join(f'"{w}"' if " " in w else w for w in
                        ["maintenance", "outage", "servers", "connectivity", "investigating", "downtime", "offline"])
    q = f"({froms}) ({words}) -is:retweet -is:reply"
    params = {"query": q, "max_results": 10, "tweet.fields": "created_at,author_id",
              "expansions": "author_id", "user.fields": "username"}
    # Only ask for posts newer than the last one seen — X bills per post returned.
    meta = CURRENT_STATE.setdefault("meta", {})
    if meta.get("x_since_id"):
        params["since_id"] = meta["x_since_id"]
    url = "https://api.x.com/2/tweets/search/recent?" + urllib.parse.urlencode(params)
    d = http_json(url, headers={"Authorization": f"Bearer {tok}"})
    if d.get("meta", {}).get("newest_id"):
        meta["x_since_id"] = d["meta"]["newest_id"]
    users = {u["id"]: u["username"] for u in d.get("includes", {}).get("users", [])}
    res = SourceResult()
    for t in d.get("data", []):
        user = users.get(t.get("author_id"), "?")
        game = next((g for u, g in config.X_ACCOUNTS.items() if u.lower() == user.lower()), user)
        text = t.get("text", "")
        if game == "Call of Duty" and cod_only_ignored_modes(text):
            continue
        posted = iso(t.get("created_at")) or datetime.now(timezone.utc)
        start, end, _ = parse_pacific_window(text, posted)
        res.announcements.append(Announcement(
            key=f"x:{t['id']}", game=game, title=f"@{user} on X", text=clip(text, 400),
            url=f"https://x.com/{user}/status/{t['id']}",
            kind="maintenance" if has_any(text, config.MAINTENANCE_WORDS) and not has_any(text, ["emergency"]) else "outage",
            start=start, end=end, posted_at=posted))
    res.summary = f"{len(res.announcements)} matching post(s)"
    return res


class SkipSource(Exception):
    pass


CURRENT_STATE: dict = {}   # set by run() so sources (X) can keep a cursor


SOURCES = {
    "EA (Madden/FC)": src_ea,
    "Activision (CoD)": src_activision,
    "NBA 2K": lambda: src_statuspage(config.NBA2K_STATUSPAGE, "NBA 2K", config.NBA2K_PRIORITY_COMPONENTS),
    "CS2 (Valve)": src_cs2,
    "Street Fighter 6": src_sf6,
    "TEKKEN 8": src_tekken,
    "Steam news": src_steam_news,
    "X / Twitter": src_x,
}
CONFIRM_RUNS = {"CS2 (Valve)": config.CS2_CONFIRM_RUNS}


# ════════════════════════════════════════════════════════════════════════
# Slack
# ════════════════════════════════════════════════════════════════════════
def slack_time(dt: datetime) -> str:
    """Renders in each viewer's own timezone inside Slack; PT fallback."""
    ts = int(dt.timestamp())
    fb = dt.astimezone(PT).strftime("%a %b %-d, %-I:%M %p PT")
    return f"<!date^{ts}^{{date_short_pretty}} {{time}}|{fb}>"


class Slack:
    def __init__(self, dry: bool):
        self.dry = dry
        self.url = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
        self.mention = os.environ.get("SLACK_MENTION", "").strip()   # e.g. <!here>
        self.sent = 0
        if not dry and not self.url:
            sys.exit("SLACK_WEBHOOK_URL is not set (use --dry-run to test without Slack).")

    def post(self, text: str, *, loud: bool = False, color: str = "#888888", plain: bool = False):
        if loud and self.mention:
            text = f"{self.mention} {text}"
        self.sent += 1
        if self.dry:
            print("─" * 60 + "\n" + text + "\n")
            return
        payload = ({"text": text} if plain else
                   {"text": text.split("\n")[0],
                    "attachments": [{"color": color, "mrkdwn_in": ["text"], "text": text}]})
        for attempt in range(3):
            try:
                req = urllib.request.Request(self.url, data=json.dumps(payload).encode(),
                                             headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=15).read()
                return
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    time.sleep(int(e.headers.get("Retry-After", "2")))
                    continue
                print(f"Slack error {e.code}: {e.read()[:200]}", file=sys.stderr)
                return
            except Exception as e:
                print(f"Slack error: {e}", file=sys.stderr)
                time.sleep(2)


ICON = {"outage": "🔴", "degraded": "🟠", "maintenance": "🛠️", "info": "ℹ️"}
COLOR = {"outage": "#E01E5A", "degraded": "#ECB22E", "maintenance": "#1D9BD1",
         "resolved": "#2EB67D", "info": "#888888"}


def fmt_issue_new(i: Issue) -> str:
    head = {"outage": "SERVER ISSUE", "degraded": "DEGRADED", "maintenance": "MAINTENANCE LIVE"}[i.kind]
    s = f"{ICON[i.kind]} *{head} — {i.game}*\n{i.title}"
    if i.detail:
        s += f"\n{i.detail}"
    if i.url:
        s += f"\n<{i.url}|Source>"
    return s


def fmt_issue_update(i: Issue) -> str:
    s = f"🔄 *Update — {i.game}*\n{i.title}"
    if i.detail:
        s += f"\n{i.detail}"
    if i.url:
        s += f"\n<{i.url}|Source>"
    return s


def fmt_issue_resolved(prev: dict, started: float) -> str:
    mins = int((time.time() - started) / 60)
    dur = f"{mins // 60}h {mins % 60}m" if mins >= 60 else f"{mins}m"
    return f"✅ *Cleared — {prev['game']}*\n{prev['title']}\n_No longer reported (≈{dur} since first alert)._"


def plan_reminders(start: datetime, now: datetime) -> list[float]:
    """Hours-before-start at which to remind, given when we learned about it."""
    lead_h = (start - now).total_seconds() / 3600
    plan = []
    for h in sorted(config.REMINDER_TIERS_HOURS, reverse=True):
        if lead_h - h >= config.REMINDER_MIN_GAP_HOURS:
            plan.append(h)
            break
    f = config.FINAL_REMINDER_HOURS
    if f and f not in plan and lead_h - f >= config.REMINDER_MIN_GAP_HOURS:
        plan.append(f)
    return plan


def fmt_lead(hours: float) -> str:
    mins = max(int(round(hours * 60)), 1)
    if mins == 60:
        return "1 hour"
    if mins < 90:
        return f"{mins} min"
    h = round(mins / 60, 1)
    return f"{int(h) if h == int(h) else h} hours"


def fmt_announcement(a: Announcement, plan: list[float] | None = None) -> str:
    head = {"maintenance": "PLANNED MAINTENANCE", "outage": "OUTAGE NOTICE", "info": "NOTICE"}[a.kind]
    s = f"{ICON.get(a.kind, 'ℹ️')} *{head} — {a.game}*\n*{a.title}*"
    if a.start:
        s += f"\n🗓️ {slack_time(a.start)}" + (f" → {slack_time(a.end)}" if a.end else "")
    if a.text:
        s += f"\n> {a.text.replace(chr(10), chr(10) + '> ')}"
    if a.url:
        s += f"\n<{a.url}|Full notice>"
    if plan:
        s += "\n_I'll remind you " + " and ".join(f"{fmt_lead(h)}" for h in plan) + " before it starts._"
    return s


# ════════════════════════════════════════════════════════════════════════
# Engine
# ════════════════════════════════════════════════════════════════════════
def load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(st: dict):
    st.setdefault("meta", {})
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f, indent=1, sort_keys=True, default=str)
    os.replace(tmp, STATE_FILE)


def run(dry: bool = False, only: list[str] | None = None, fetchers: dict | None = None,
        now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    st = load_state()
    st.setdefault("issues", {})       # key -> {game,title,fp,since,source,pending}
    st.setdefault("seen", {})         # source -> [announcement keys]
    st.setdefault("upcoming", {})     # key -> {game,title,start,end,url,reminders}
    st.setdefault("fails", {})        # source -> consecutive failure count
    st.setdefault("meta", {})
    global CURRENT_STATE
    CURRENT_STATE = st
    slack = Slack(dry)
    fetchers = fetchers or SOURCES

    for name, fn in fetchers.items():
        if only and name not in only:
            continue
        try:
            res = fn()
        except SkipSource as e:
            print(f"[skip] {name}: {e}")
            continue
        except Exception as e:
            n = st["fails"].get(name, 0) + 1
            st["fails"][name] = n
            print(f"[fail {n}] {name}: {e}", file=sys.stderr)
            if os.environ.get("DEBUG"):
                traceback.print_exc()
            if n == config.SOURCE_FAIL_WARN_AFTER:
                slack.post(f"⚠️ *Watcher can't reach {name}*\n{n} checks in a row failed "
                           f"(`{clip(str(e), 150)}`). Outages for this game won't be caught "
                           f"until it recovers.", color=COLOR["degraded"])
            continue

        if st["fails"].get(name, 0) >= config.SOURCE_FAIL_WARN_AFTER:
            slack.post(f"👍 *Watcher reconnected to {name}.*", color=COLOR["resolved"])
        st["fails"][name] = 0
        print(f"[ok] {name}: {res.summary}")

        # ── live issues: new / changed / cleared ──────────────────────────
        confirm = CONFIRM_RUNS.get(name, 1)
        current = {i.key: i for i in res.issues}
        for key, i in current.items():
            prev = st["issues"].get(key)
            if prev is None:
                prev = st["issues"][key] = {"game": i.game, "title": i.title, "fp": i.fp(),
                                            "since": time.time(), "source": name,
                                            "seen_runs": 0, "alerted": False}
            prev["seen_runs"] = prev.get("seen_runs", 0) + 1
            if not prev["alerted"]:
                if prev["seen_runs"] >= confirm:
                    slack.post(fmt_issue_new(i), loud=i.loud and i.kind != "maintenance",
                               color=COLOR[i.kind])
                    prev.update(alerted=True, fp=i.fp(), title=i.title, since=time.time())
            elif prev["fp"] != i.fp():
                slack.post(fmt_issue_update(i), color=COLOR[i.kind])
                prev.update(fp=i.fp(), title=i.title)
        for key in [k for k, v in st["issues"].items() if v.get("source") == name and k not in current]:
            prev = st["issues"].pop(key)
            if prev.get("alerted"):
                slack.post(fmt_issue_resolved(prev, prev["since"]), color=COLOR["resolved"])

        # ── announcements: post once ──────────────────────────────────────
        first_time = name not in st["seen"]
        seen = set(st["seen"].get(name, []))
        for a in res.announcements:
            if a.key in seen:
                continue
            seen.add(a.key)
            future = a.start is not None and (a.end or a.start) > now
            # On the very first run, don't dump old history — only things still ahead.
            if first_time and not future:
                continue
            # Old posts discovered late (e.g. feed re-ordered) — skip if >3 days old & not upcoming.
            if a.posted_at and (now - a.posted_at) > timedelta(days=3) and not future:
                continue
            # Same maintenance announced by two sources (e.g. Capcom site + Steam news)? Post once.
            if future and any(u["game"] == a.game and abs((iso(u["start"]) - a.start).total_seconds()) < 1800
                              for u in st["upcoming"].values()):
                continue
            plan = plan_reminders(a.start, now) if future and a.start > now else []
            slack.post(fmt_announcement(a, plan), loud=(a.kind == "outage"),
                       color=COLOR.get(a.kind, COLOR["info"]))
            if future:
                st["upcoming"][a.key] = {"game": a.game, "title": a.title, "url": a.url,
                                         "start": a.start.isoformat(),
                                         "end": a.end.isoformat() if a.end else None,
                                         "reminders": plan}
        st["seen"][name] = sorted(seen)[-300:]

    # ── reminders before planned maintenance ──────────────────────────────
    for key, u in list(st["upcoming"].items()):
        start = iso(u["start"])
        end = iso(u.get("end")) or (start + timedelta(hours=6) if start else None)
        if not start or now > end + timedelta(hours=12):
            st["upcoming"].pop(key, None)
            continue
        if "reminders" not in u:   # entry saved by an older version
            u["reminders"] = [] if u.pop("reminded", False) else plan_reminders(start, now)
        lead_h = (start - now).total_seconds() / 3600
        due = [h for h in u["reminders"] if lead_h <= h]
        if not due:
            continue
        u["reminders"] = [h for h in u["reminders"] if h not in due]
        if lead_h <= 0:
            continue   # already started (e.g. watcher was down) — don't post late
        # If several are due at once (watcher was down), send just one.
        slack.post(f"⏰ *Maintenance in ~{fmt_lead(lead_h)} — {u['game']}*\n{u['title']}\n"
                   f"🗓️ {slack_time(start)}" + (f" → {slack_time(end)}" if u.get('end') else "")
                   + (f"\n<{u['url']}|Notice>" if u.get("url") else ""),
                   loud=True, color=COLOR["maintenance"])

    # state.json is committed back to the repo only when it changes. Bump a
    # keepalive monthly so GitHub never pauses the schedule for inactivity.
    ka = iso(st["meta"].get("keepalive"))
    if not ka or now - ka > timedelta(days=30):
        st["meta"]["keepalive"] = now.isoformat()
    save_state(st)
    print(f"Done. {slack.sent} Slack message(s).")
    return st


def print_status():
    for name, fn in SOURCES.items():
        try:
            r = fn()
            print(f"✓ {name}: {r.summary}")
            for i in r.issues:
                print(f"    {ICON[i.kind]} {i.game}: {i.title}")
            for a in r.announcements:
                when = a.start.astimezone(PT).strftime("%b %-d %-I:%M%p PT") if a.start else "no time parsed"
                print(f"    🗒  {a.game}: {a.title} [{when}]")
        except SkipSource as e:
            print(f"- {name}: skipped ({e})")
        except Exception as e:
            print(f"✗ {name}: {e}")


INTRO_MESSAGE = (
    "*Hi team, I'm Server Watch.*\n"
    "I keep an eye on server status for Madden, FC, NBA 2K, Call of Duty, CS2, TEKKEN 8 and "
    "Street Fighter 6. When servers go down, come back up, or maintenance gets announced, I post "
    "here right away, then remind you ahead of maintenance (12 hours out when possible) so you can "
    "plan matches around it."
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--test-slack", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--intro", action="store_true")
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    if a.test_slack:
        Slack(False).post("✅ *Server Watch is connected.* Outage + maintenance alerts for "
                          "Madden, FC, NBA 2K, CoD, CS2, TEKKEN 8 and SF6 will land here.",
                          color=COLOR["resolved"])
        return
    if a.intro:
        Slack(False).post(INTRO_MESSAGE, plain=True)
        return
    if a.status:
        print_status()
        return
    run(dry=a.dry_run, only=a.only)


if __name__ == "__main__":
    main()
