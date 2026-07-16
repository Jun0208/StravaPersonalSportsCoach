# StravaPersonalSportsCoach

An automated weekly pipeline: pulls your Strava activity data, analyzes
running performance and trends, generates an AI athlete-coach summary and
next week's training plan, publishes a dashboard via GitHub Pages, and
emails you the report every Monday.

See [SETUP.md](SETUP.md) for the one-time setup checklist (Strava API app,
GitHub secrets, Gmail App Password, GitHub Pages).

## Repo layout

- `scripts/extract_strava.py` — pulls activities from the Strava API into `data/activities.db` (SQLite), deduped by activity ID.
- `scripts/strava_oauth_helper.py` — one-time local script to get a Strava refresh token.
- `scripts/analyze.py` — computes this week's running stats vs. historical trend, writes `data/weekly_summary.json` and appends to `data/weekly_history.csv`.
- `scripts/build_report.py` — renders the dashboard (`docs/index.html` + `docs/reports/<week>.html`) for GitHub Pages.
- `scripts/send_email.py` — sends the weekly report via Gmail SMTP.
- `.github/workflows/weekly-extract.yml` — Monday cron: extract → analyze → build dashboard → commit.
- `.github/workflows/send-email.yml` — fires once the AI coach narrative is written, sends the email.