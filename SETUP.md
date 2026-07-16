# Setup

This is a one-time checklist to get the pipeline running. Everything after
this is automatic (weekly, Monday ~9am UK time).

## How it works (architecture)

```
                     ┌─────────────────────────┐
Mon 08:00 UK ──────▶ │ GitHub Actions           │  full internet access, so this is
                     │ weekly-extract.yml       │  where the Strava API calls happen
                     │  - pull new activities   │
                     │  - store in data/*.db    │
                     │  - compute weekly stats  │
                     │  - build dashboard HTML  │
                     └───────────┬─────────────┘
                                 │ commits data/ + docs/
                                 ▼
                     ┌─────────────────────────┐
Mon ~08:00-09:00 UK ▶│ Claude Code Remote       │  reads the fresh stats, writes the
                     │ scheduled routine        │  "how am I doing / insights / next
                     │  - deep coach analysis   │  week's plan" narrative -- this is
                     │  - writes narrative      │  the part that benefits from actual
                     │  - commits + pushes      │  reasoning, not a canned template
                     └───────────┬─────────────┘
                                 │ push triggers on data/coach_narrative.md
                                 ▼
                     ┌─────────────────────────┐
                     │ GitHub Actions           │
                     │ send-email.yml           │  emails you the summary + narrative
                     │  - send via Gmail SMTP   │  + a link to the full dashboard
                     └─────────────────────────┘
                                 │
                                 ▼
                     GitHub Pages serves docs/ as your public
                     athlete blog (index.html = latest week,
                     docs/reports/*.html = archive)
```

Why two engines: this Claude Code session runs in a sandboxed environment
whose network policy blocks outbound access to strava.com entirely (I
confirmed this directly -- confirmed working, please note it may be
different for you if you re-run in a different environment). GitHub
Actions runners have normal, unrestricted internet, so the actual Strava
extraction has to live there. The AI narrative doesn't need Strava access
at that point (the data's already been pulled into the repo), so it can
run wherever Claude has time -- reusing this Claude Code Remote session
avoids needing a separate Anthropic API billing account.

## 1. Register a Strava API application (you have to do this)

1. Go to **https://www.strava.com/settings/api** while logged into your
   Strava account.
2. Create an application. For "Authorization Callback Domain" enter
   `localhost`.
3. Note the **Client ID** and **Client Secret** shown.

Source: [Strava API authentication docs](https://developers.strava.com/docs/authentication/).

## 2. Get a refresh token (one-time, run on your own machine)

This session can't reach strava.com, so this step has to happen on a
computer with normal internet access -- your laptop is fine.

```bash
git clone <this repo> && cd StravaPersonalSportsCoach
pip install requests
python3 scripts/strava_oauth_helper.py --client-id YOUR_CLIENT_ID --client-secret YOUR_CLIENT_SECRET
```

Follow the prompts: it prints a URL, you open it in a browser, click
"Authorize" (this grants the `activity:read_all` scope, needed to include
private activities -- plain `read` only exposes public ones), then paste
the redirect URL back into the terminal. It prints three values.

## 3. Add GitHub repository secrets

Repo → **Settings → Secrets and variables → Actions → New repository
secret**. Add:

| Secret | Value |
|---|---|
| `STRAVA_CLIENT_ID` | from step 1 |
| `STRAVA_CLIENT_SECRET` | from step 1 |
| `STRAVA_REFRESH_TOKEN` | from step 2 |
| `GMAIL_ADDRESS` | the Gmail address to send from |
| `GMAIL_APP_PASSWORD` | see step 4 |
| `RECIPIENT_EMAIL` | where the weekly report should land (can be the same Gmail address) |

## 4. Create a Gmail App Password

Regular Gmail passwords don't work for SMTP from a script. You need an
App Password:

1. Enable 2-Step Verification on the Google account, if not already on:
   **https://myaccount.google.com/signinoptions/two-step-verification**
2. Generate an App Password: **https://myaccount.google.com/apppasswords**
   (pick "Mail" / "Other", name it e.g. "strava-coach").
3. Use the 16-character generated password as `GMAIL_APP_PASSWORD` above
   (not your normal Google password).

## 5. Enable GitHub Pages

Repo → **Settings → Pages** → Source: **Deploy from a branch** → Branch:
`main`, folder: `/docs`.

Your dashboard will be at `https://<your-github-username>.github.io/<repo-name>/`.
**Note:** this makes the dashboard (your run history, pace, etc.) publicly
viewable at that URL -- there's no login. If you'd rather it not be public,
tell me and we'll switch the "blog" step to email-only instead.

## 6. Run the first full extract

The first run should pull your *entire* Strava history (not just last
week) so there's a real baseline to compare against. Once secrets are set:

Repo → **Actions → Weekly Strava Extract → Run workflow** → set `full` to
`true` → **Run workflow**.

Check the run logs. If it succeeds, `data/activities.db` and
`docs/index.html` will be committed automatically.

## 7. I'll set up the weekly Claude Code Remote routine

Once steps 1-6 are done and the first full extract has succeeded, tell me
and I'll create the scheduled routine that writes the weekly coach
narrative and triggers the email. That part happens automatically on my
side once I create it (no manual code repo config needed for the
Claude-side scheduling) -- I mention it here just so the whole flow is
documented in one place.

## Known limitations / things worth knowing

- **DST**: the schedules approximate 8-9am UK time using two fixed UTC
  cron entries (one for BST months, one for GMT months). In the exact week
  clocks change (last Sunday of March / October) it can be off by up to an
  hour for a single run.
- **Refresh token rotation**: Strava *can* issue a new refresh token on
  a refresh call. `extract_strava.py` doesn't auto-update the GitHub
  secret (that would need broader repo permissions than this project
  should hold) -- if extraction ever starts failing with an auth error,
  regenerate the token with `strava_oauth_helper.py` and update the
  `STRAVA_REFRESH_TOKEN` secret.
- **Rate limits**: Strava's published defaults are roughly 200
  requests/15 min and 2,000/day per app -- fine for weekly incremental
  syncs; the first full-history pull could get close to this if you have
  a very large activity history, in which case the script will back off
  and retry automatically on a 429.
- **Data storage**: activity data lives as a SQLite file committed to
  this repo (`data/activities.db`). That means your raw activity history
  is in the repo's git history -- keep the repo private if you don't want
  that visible, independent of the Pages-visibility question in step 5.
