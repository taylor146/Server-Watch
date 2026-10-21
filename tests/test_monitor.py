"""
Offline tests: feed each source the payload shapes captured from the live
feeds on 2026-10-21, and check the alert engine end to end.
Run:  python -m unittest discover -s tests -v
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import monitor  # noqa: E402

UTC = timezone.utc

EA = {"response": {"madden-nfl-27": "Some Issues", "fc-26": "Online", "fc-27": "Online",
                   "ea-app": "Online", "nhl-27": "Online"}, "timestamp": "2026-10-21T19:05:33Z"}
EA_ALERTS = {"response": [], "timestamp": "2026-10-21T19:05:33Z"}

ATVI = {"updatedTime": "2026-10-21T19:03:40.189Z", "issuesListRO": [
    {"Id": "a0iKe000000kIZ7IAM", "Name": "Player Support Test Alert",
     "OSHP_Game_Title__c": "Call of Duty: Black Ops 7", "OSHP_Platform__c": "Xbox 360",
     "OSHP_Event_Subject__c": "test", "LastModifiedDate": "2025-06-02T16:08:28.000+0000"},
    {"Id": "a0iKe000000kttzIAA", "Name": "Demonware Updated Incident Notification",
     "OSHP_Event_ID__c": "2025091845", "OSHP_Game_Title__c": "Crash Team Racing Nitro-Fueled",
     "OSHP_Platform__c": "Xbox One;PlayStation 4", "OSHP_Event_Subject__c": "Connectivity drop",
     "LastModifiedDate": "2025-09-18T09:56:18.000+0000"},
    {"Id": "COD1", "Name": "Demonware Initial Incident Notification: [#2026102101]",
     "OSHP_Event_ID__c": "2026102101", "OSHP_Game_Title__c": "Call of Duty: Black Ops 7;Call of Duty: Warzone",
     "OSHP_Platform__c": "PlayStation 5;Xbox Series X|S;Battle.net",
     "OSHP_Event_Subject__c": "Matchmaking issues on listed titles",
     "OSHP_Event_Description__c": "We are investigating reports of players unable to connect.",
     "LastModifiedDate": "2026-10-21T18:00:00.000+0000"},
]}

SP = {"status": {"indicator": "minor", "description": "Partial System Outage"},
      "components": [
          {"id": "g1", "name": "Game Modes", "status": "partial_outage", "group": True},
          {"id": "c1", "name": "Play With Friends", "status": "partial_outage", "group_id": "g1"},
          {"id": "c2", "name": "MyPARK", "status": "operational", "group_id": "g1"},
          {"id": "c3", "name": "2KTV", "status": "degraded_performance", "group_id": "g1"}],
      "incidents": [{"id": "i1", "name": "Play With Friends disconnects", "impact": "minor",
                     "status": "investigating", "shortlink": "https://stspg.io/x",
                     "incident_updates": [{"id": "u1", "status": "investigating",
                                           "body": "We are aware of disconnects."}]}],
      "scheduled_maintenances": [{"id": "m1", "name": "Server maintenance", "status": "scheduled",
                                  "scheduled_for": "2026-10-23T08:00:00.000Z",
                                  "scheduled_until": "2026-10-23T10:00:00.000Z",
                                  "shortlink": "https://stspg.io/m", "incident_updates": [
                                      {"id": "mu1", "body": "Servers offline for 2 hours."}]}]}

SF6_BODY_MAINT = ("Maintenance has been scheduled. Please see below for further information.\r\n \r\n"
                  "<h5>Maintenance Period</h5>\r\nTuesday, October 27, 11:00 a.m. – 4:00 p.m. JST\r\n"
                  "Monday, October 26, 7:00 p.m. – 12:00 a.m. PDT\r\n"
                  "Tuesday, October 27, 2:00 a.m. – 7:00 a.m. UTC\r\n")
SF6_LIST = {"props": {"pageProps": {"info_list": [
    {"title": "Maintenance Notice", "category": "Update/Maintenance", "categorySlug": "update_maintenance",
     "slug": "mainte20261027", "body": SF6_BODY_MAINT, "releaseDate": 1792800000},   # Oct 22 2026
    {"title": "Update Notice", "category": "Update/Maintenance", "categorySlug": "update_maintenance",
     "slug": "update20261013", "body": "updated", "releaseDate": 1791873913},
    {"title": "Maintenance Notice", "category": "Update/Maintenance", "categorySlug": "update_maintenance",
     "slug": "mainte20261013", "body": SF6_BODY_MAINT.replace("27", "13").replace("26", "12"),
     "releaseDate": 1791510346},
]}}}
SF6_HTML = f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(SF6_LIST)}</script></html>'

TEKKEN = {"data": {"articles": [
    {"id": "t1", "title": "TEKKEN 8 Patch Notes v3.03", "slug": "tekken-8-patch-notes-v3-03",
     "date": "2026-10-22T07:00:00+00:00", "external_url": None, "content": {"content":
        "<p>Maintenance Schedule</p><p>[CEST] Thursday, October 29th, 3:30 AM – 6:00 AM</p>"
        "<p>[PDT] Wednesday, October 28th, 6:30 PM – 9:00 PM</p><p>Note: subject to change.</p>"}},
    {"id": "t2", "title": "TEKKEN 8 Kicks Off Roger Jr.", "slug": "x", "date": "2026-10-12T13:00:00+00:00",
     "external_url": None, "content": {"content": "<p>Roger Jr. arrives!</p>"}},
]}}

CS2_OK = {"result": {"services": {"SessionsLogon": "normal", "SteamCommunity": "normal"},
                     "matchmaking": {"scheduler": "normal", "online_players": 900000},
                     "datacenters": {"US Seattle": {"capacity": "full", "load": "low"}}}}
CS2_BAD = {"result": {"services": {"SessionsLogon": "offline", "SteamCommunity": "normal"},
                      "matchmaking": {"scheduler": "offline"},
                      "datacenters": {"US Seattle": {"capacity": "offline", "load": "offline"}}}}

STEAM = {"appnews": {"newsitems": [
    {"gid": "1", "title": "Scheduled server maintenance", "url": "https://store.steampowered.com/news/1",
     "contents": "[p]Servers will be offline for maintenance on Monday, October 26, 7:00 p.m. – 9:00 p.m. PDT[/p]",
     "date": 1792800000},
    {"gid": "2", "title": "New fighter trailer", "url": "u", "contents": "Look at this!", "date": 1792800000}]}}


def fake_http_json(url, **kw):
    if "server-statuses" in url:
        return EA
    if "playershell" in url:
        return EA_ALERTS
    if "oshp/landingpage" in url:
        return ATVI
    if "summary.json" in url:
        return SP
    if "hygraph" in url:
        return TEKKEN
    if "ICSGOServers" in url:
        return fake_http_json.cs2
    if "ISteamNews" in url:
        return STEAM if "1364780" in url else {"appnews": {"newsitems": []}}
    raise AssertionError(url)


fake_http_json.cs2 = CS2_OK


def fake_http(url, **kw):
    if "streetfighter.com" in url:
        return SF6_HTML
    raise AssertionError(url)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        monitor.STATE_FILE = os.path.join(self.tmp, "state.json")
        os.environ["STEAM_API_KEY"] = "x"
        os.environ.pop("X_BEARER_TOKEN", None)
        os.environ["SLACK_MENTION"] = "<!here>"
        fake_http_json.cs2 = CS2_OK
        self.p1 = mock.patch.object(monitor, "http_json", fake_http_json)
        self.p2 = mock.patch.object(monitor, "http", fake_http)
        self.p1.start(); self.p2.start()
        self.posts = []
        self.p3 = mock.patch.object(monitor.Slack, "post",
                                    lambda s, text, loud=False, color="": (self.posts.append((text, loud)),
                                                                           setattr(s, "sent", s.sent + 1)))
        self.p3.start()

    def tearDown(self):
        mock.patch.stopall()

    def texts(self):
        return "\n=====\n".join(t for t, _ in self.posts)


class TestTimeParsing(Base):
    def test_capcom(self):
        ref = datetime(2026, 10, 22, tzinfo=UTC)
        s, e, _ = monitor.parse_pacific_window("Monday, October 26, 7:00 p.m. – 12:00 a.m. PDT", ref)
        self.assertEqual((s.month, s.day, s.hour), (10, 26, 19))
        self.assertEqual((e.day, e.hour), (27, 0))

    def test_bandai(self):
        ref = datetime(2026, 9, 9, tzinfo=UTC)
        s, e, _ = monitor.parse_pacific_window("[CEST] Thursday, September 10th, 3:30 AM – 6:00 AM "
                                               "[PDT] Wednesday, September 9th, 6:30 PM – 9:00 PM", ref)
        self.assertEqual((s.day, s.hour, s.minute, e.hour), (9, 18, 30, 21))

    def test_year_rollover(self):
        ref = datetime(2026, 12, 30, tzinfo=UTC)
        s, _, _ = monitor.parse_pacific_window("Monday, January 4, 7:00 p.m. – 9:00 p.m. PST", ref)
        self.assertEqual(s.year, 2027)


class TestEngine(Base):
    NOW = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)

    def test_first_run(self):
        monitor.run(dry=True, fetchers=self._fetchers(), now=self.NOW)
        t = self.texts()
        print("\n\n######## FIRST RUN — Slack messages ########\n" + t)
        self.assertIn("Madden NFL 27", t)                      # EA Some Issues
        self.assertIn("Matchmaking issues on listed titles", t)  # CoD
        self.assertNotIn("Crash Team Racing", t)               # not a watched game
        self.assertNotIn("Test Alert", t)
        self.assertIn("Play With Friends", t)                  # 2K component
        self.assertIn("Scheduled maintenance: Server maintenance", t)  # 2K planned
        self.assertIn("mainte20261027", t)                     # SF6 upcoming notice
        self.assertNotIn("mainte20261013", t)                  # SF6 old notice, past
        self.assertNotIn("Update Notice", t)
        self.assertIn("TEKKEN 8 Patch Notes v3.03", t)         # Tekken upcoming
        self.assertNotIn("Roger Jr", t)
        self.assertNotIn("Scheduled server maintenance", t)    # Steam dup of SF6 notice suppressed
        # loud mention on real outages
        self.assertTrue(any(l for txt, l in self.posts if "Matchmaking issues" in txt))
        # Play With Friends is priority -> loud; 2KTV is not
        self.assertTrue(any(l for txt, l in self.posts if "Play With Friends (Game Modes) —" in txt))
        # SF6 maintenance announced by both Capcom and Steam -> posted once
        self.assertEqual(sum("Street Fighter 6" in t and "PLANNED" in t for t, _ in self.posts), 1)
        self.assertFalse(any(l for txt, l in self.posts if "2KTV" in txt))

    def test_second_run_quiet_then_resolve_and_remind(self):
        f = self._fetchers()
        monitor.run(dry=True, fetchers=f, now=self.NOW)
        self.posts.clear()
        monitor.run(dry=True, fetchers=f, now=self.NOW)
        self.assertEqual(self.posts, [], "no duplicate alerts on an unchanged second run")

        # Madden recovers
        EA["response"]["madden-nfl-27"] = "Online"
        try:
            monitor.run(dry=True, fetchers=f, now=self.NOW)
        finally:
            EA["response"]["madden-nfl-27"] = "Some Issues"
        self.assertTrue(any("✅" in t and "Madden" in t for t, _ in self.posts))

        # 45 min before SF6 maintenance (Oct 26 7pm PDT = Oct 27 02:00 UTC)
        self.posts.clear()
        monitor.run(dry=True, fetchers=f, now=datetime(2026, 10, 27, 1, 15, tzinfo=UTC))
        reminders = [t for t, _ in self.posts if t.startswith("⏰")]
        print("\n\n######## REMINDER ########\n" + "\n".join(reminders))
        self.assertTrue(any("Street Fighter 6" in t for t in reminders))

    def test_cs2_debounce(self):
        f = self._fetchers()
        monitor.run(dry=True, fetchers=f, now=self.NOW)
        self.posts.clear()
        fake_http_json.cs2 = CS2_BAD
        monitor.run(dry=True, fetchers={"CS2 (Valve)": monitor.src_cs2}, now=self.NOW)
        self.assertEqual(self.posts, [], "one bad CS2 reading should not alert")
        monitor.run(dry=True, fetchers={"CS2 (Valve)": monitor.src_cs2}, now=self.NOW)
        self.assertTrue(any("CS2" in t and "SessionsLogon" in t for t, _ in self.posts))

    def test_source_failure_warning(self):
        def boom():
            raise RuntimeError("403 Forbidden")
        for _ in range(monitor.config.SOURCE_FAIL_WARN_AFTER):
            monitor.run(dry=True, fetchers={"Activision (CoD)": boom}, now=self.NOW)
        self.assertEqual(sum("can't reach" in t for t, _ in self.posts), 1)
        monitor.run(dry=True, fetchers={"Activision (CoD)": monitor.src_activision}, now=self.NOW)
        self.assertTrue(any("reconnected" in t for t, _ in self.posts))

    def test_cod_mode_filter(self):
        f = monitor.cod_only_ignored_modes
        self.assertTrue(f("Warzone players may experience matchmaking delays"))
        self.assertTrue(f("We're aware of DMZ exfil issues on Modern Warfare 4"))
        self.assertTrue(f("Warzone and DMZ servers are down for maintenance"))
        self.assertFalse(f("Multiplayer and Warzone players unable to connect"))
        self.assertFalse(f("Connectivity drop across listed titles"))     # no mode named -> keep
        self.assertFalse(f("Warzone and Multiplayer login issues"))

        extra = dict(ATVI)
        extra["issuesListRO"] = ATVI["issuesListRO"] + [
            {"Id": "WZ1", "Name": "Warzone incident", "OSHP_Game_Title__c": "Call of Duty: Black Ops 7;Call of Duty: Warzone",
             "OSHP_Event_Subject__c": "Warzone matchmaking degraded", "OSHP_Event_Description__c": "Investigating Warzone queues.",
             "OSHP_Platform__c": "PlayStation 5", "LastModifiedDate": "2026-10-21T18:00:00.000+0000"},
            {"Id": "WZ2", "Name": "Warzone only", "OSHP_Game_Title__c": "Call of Duty: Warzone",
             "OSHP_Event_Subject__c": "Login issues", "OSHP_Platform__c": "Xbox", "LastModifiedDate": "x"}]
        with mock.patch.object(monitor, "http_json", lambda u, **k: extra):
            titles = [i.title for i in monitor.src_activision().issues]
        self.assertEqual(titles, ["Matchmaking issues on listed titles"])

    def test_x_uses_since_id(self):
        os.environ["X_BEARER_TOKEN"] = "t"
        calls = []

        def fake(url, **kw):
            calls.append(url)
            if len(calls) == 1:
                return {"data": [{"id": "500", "author_id": "u1", "created_at": "2026-10-22T11:00:00Z",
                                  "text": "Street Fighter 6 emergency maintenance is underway. Servers offline."}],
                        "includes": {"users": [{"id": "u1", "username": "StreetFighter"}]},
                        "meta": {"newest_id": "500"}}
            return {"meta": {"result_count": 0}}
        with mock.patch.object(monitor, "http_json", fake):
            monitor.run(dry=True, fetchers={"X / Twitter": monitor.src_x}, now=self.NOW)
            monitor.run(dry=True, fetchers={"X / Twitter": monitor.src_x}, now=self.NOW)
        self.assertNotIn("since_id", calls[0])
        self.assertIn("since_id=500", calls[1])

    def _fetchers(self):
        f = dict(monitor.SOURCES)
        f.pop("X / Twitter")
        return f


if __name__ == "__main__":
    unittest.main()
