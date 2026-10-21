# Server Watch

Pings a Slack channel when servers have problems in any of 1v1Me's seven
leagues, and when **planned maintenance** gets announced. Sends a reminder
60 minutes before it starts.

| Game | Where it checks | Live outages | Planned maintenance |
|---|---|---|---|
| Madden NFL 27 | EA server-status feed + EA banner alerts | ✅ | ✅ (when EA posts a banner) |
| EA SPORTS FC 26 / 27 | Same EA feed | ✅ | ✅ (when EA posts a banner) |
| NBA 2K | 2K's status page (incidents, each game mode) | ✅ | ✅ with start/end times |
| Call of Duty (BO7, MW4, Warzone) | Activision's Online Services feed | ✅ | ✅ (when posted as an event) |
| CS2 | Valve's game-coordinator status + Steam news | ✅ | ✅ (from Steam news) |
| Street Fighter 6 | Capcom's Buckler's Boot Camp notices + Steam news | ✅ (Outage Info posts) | ✅ usually days ahead |
| TEKKEN 8 | Bandai Namco news (patch notes list the maintenance window) + Steam news | — | ✅ (often same-day) |
| *(optional)* official X accounts | @EAHelp, @ATVIAssist, @CODUpdates, @NBA2K, @CounterStrike, @StreetFighter, @TEKKEN | ✅ | ✅ |

### What shows up in Slack

- 🔴 **Server issue** / 🟠 **Degraded**: the channel gets an @-mention if you set one up
- 🔄 **Update**: the publisher changed what it's saying about the issue
- ✅ **Cleared**: shows roughly how long the issue lasted
- 🛠️ **Planned maintenance**: the start and end times show in each viewer's own time zone
- ⏰ **Maintenance in ~60 min**: reminder before it starts
- ⚠️ **Watcher can't reach X**: one source has failed for about 30 minutes, so the watcher can't see that game right now

---

## Setup (about 15 minutes)

### 1. Make a Slack webhook
1. Go to https://api.slack.com/apps → **Create New App** → *From scratch* → name it "Server Watch", pick your workspace.
2. **Incoming Webhooks** → turn it on → **Add New Webhook to Workspace** → choose the channel (e.g. `#server-status`).
3. Copy the webhook URL (`https://hooks.slack.com/services/...`).

### 2. Get a Steam Web API key (free, used for CS2)
https://steamcommunity.com/dev/apikey. Any domain name works (e.g. `1v1me.com`).

### 3. Put this code in a GitHub repo
1. Create a new repo on GitHub. **Make it public**: public repos get unlimited
   free Actions minutes. A private repo checking every 5 minutes would use up the
   free 2,000 min/month in about a week. Nothing secret lives in the code; keys go in step 4.
2. Upload every file in this folder, including the hidden `.github` folder.
   (On the website: **Add file → Upload files**, then drag in the folder contents.)

### 4. Add the secrets
Repo → **Settings → Secrets and variables → Actions**

| Type | Name | Value |
|---|---|---|
| Secret | `SLACK_WEBHOOK_URL` | webhook from step 1 |
| Secret | `STEAM_API_KEY` | key from step 2 |
| Secret *(optional)* | `X_BEARER_TOKEN` | X API Basic plan or higher. Without it, X is skipped. |
| Variable *(optional)* | `SLACK_MENTION` | `<!here>` or `<!channel>` to ping on real outages |

### 5. Turn it on
**Actions** tab → enable workflows → **Server Watch** → **Run workflow**.
The first run posts anything that's broken right now, plus any maintenance
that's still coming up. After that it only posts when something changes.

---

## Good to know

- **Speed:** GitHub runs the check every 5 minutes, but busy periods can push a
  run 5 to 15 minutes late. For closer to 1-minute checks, have a free
  scheduler like cron-job.org trigger the workflow's `workflow_dispatch`.
- **Each new game year:** edit `config.py`. Add the new EA slug (e.g. `madden-nfl-28`),
  the new CoD title, and so on. The comments in that file show where.
- **Sources this can't see:** Tekken and SF6 announce emergency maintenance
  fastest on X. Without the X key, those show up when Bandai Namco or Capcom
  posts on their website or Steam, which can be later.
- **Check everything by hand:** `python monitor.py --status` prints what each source says right now.
- **Test Slack:** `SLACK_WEBHOOK_URL=... python monitor.py --test-slack`
- **Run the tests:** `python -m unittest discover -s tests -v`
