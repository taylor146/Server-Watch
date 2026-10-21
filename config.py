"""
Server Watch — what to monitor.

Edit this file when a new game year drops (e.g. Madden 28, FC 28, NBA 2K28,
next Call of Duty). Everything else can stay as-is.
"""

# ── EA (Madden + FC) ──────────────────────────────────────────────────────
# Keys come from EA's status feed (help.ea.com/en/server-status).
# Anything other than "Online" triggers an alert.
EA_GAMES = {
    "madden-nfl-27": "Madden NFL 27",
    "fc-26": "EA SPORTS FC 26",
    "fc-27": "EA SPORTS FC 27",
    "ea-app": "EA app (PC launcher)",
}

# ── Activision (Call of Duty) ─────────────────────────────────────────────
# Any open incident whose game title contains one of these strings alerts.
# (Warzone is deliberately left out: 1v1Me only plays Multiplayer.)
COD_TITLES = [
    "Black Ops 7",
    "Modern Warfare 4",
]

# Skip CoD incidents/posts that ONLY affect these modes. If the text also
# mentions one of COD_KEEP_WORDS (or names no mode at all), it still alerts.
COD_IGNORE_MODES = ["warzone", "dmz"]
COD_KEEP_WORDS = [
    "multiplayer", " mp ", "mp,", "all modes", "all game modes", "across modes",
    "search and destroy", "private match", "custom game", "online services",
    "battle.net", "login", "log in", "sign in",
]

# ── NBA 2K (Atlassian Statuspage) ─────────────────────────────────────────
NBA2K_STATUSPAGE = "https://nba-status.2kweb.online"
# Components that matter most for head-to-head play. These get the loud
# alert (with @-mention). Other components still alert, just without mention.
NBA2K_PRIORITY_COMPONENTS = [
    "Play With Friends",
    "Online Game",
    "PlayStation Services",
    "XBOX Live",
    "Steam",
]

# ── CS2 (Valve) ───────────────────────────────────────────────────────────
# Requires STEAM_API_KEY secret (free: https://steamcommunity.com/dev/apikey)
# Datacenters whose name starts with any of these prefixes are watched.
CS2_DATACENTER_PREFIXES = ["US "]
# Valve's status flaps. Require this many bad checks in a row before alerting.
CS2_CONFIRM_RUNS = 2

# ── Steam news feeds (planned-maintenance announcements) ──────────────────
STEAM_NEWS_APPS = {
    730: "CS2",
    1364780: "Street Fighter 6",
    1778820: "TEKKEN 8",
}

# ── Optional: X / Twitter (needs paid X API, set X_BEARER_TOKEN) ──────────
X_ACCOUNTS = {
    "EAHelp": "EA (Madden / FC)",
    "ATVIAssist": "Call of Duty",
    "CODUpdates": "Call of Duty",
    "NBA2K": "NBA 2K",
    "CounterStrike": "CS2",
    "StreetFighter": "Street Fighter 6",
    "TEKKEN": "TEKKEN 8",
}

# ── Behaviour ─────────────────────────────────────────────────────────────
# Words that mark a post as outage / maintenance related.
MAINTENANCE_WORDS = ["maintenance", "downtime", "servers will be", "offline"]
OUTAGE_WORDS = [
    "outage", "connectivity", "connection issue", "investigating",
    "servers are down", "unable to connect", "login issue", "matchmaking issue",
    "emergency maintenance",
]

# Send a heads-up this many minutes before planned maintenance starts.
REMINDER_MINUTES = 60

# Warn in Slack when a source has failed this many checks in a row
# (so you know the watcher itself is blind, not that servers are fine).
SOURCE_FAIL_WARN_AFTER = 6
