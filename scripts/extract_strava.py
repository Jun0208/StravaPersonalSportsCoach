#!/usr/bin/env python3
"""
Extract activities from the Strava API into data/activities.db (SQLite).

Modes:
  --full         Pull the athlete's entire activity history (no lower time
                 bound). Intended for the one-time first run.
  (default)      Incremental: pull only activities after the most recent
                 start_date already stored, with a 2-day overlap window so a
                 late-syncing device (e.g. a watch synced after the fact)
                 doesn't get missed. Safe because inserts are upserts keyed
                 on Strava's activity id, so overlap never creates duplicates.

Auth: refreshes a short-lived access token from a long-lived refresh token
on every run (Strava access tokens expire ~6h; refresh tokens don't expire
unless revoked). Needs env vars STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET,
STRAVA_REFRESH_TOKEN -- see scripts/strava_oauth_helper.py to obtain the
refresh token the first time.

API reference: https://developers.strava.com/docs/reference/
  GET /athlete/activities supports `before`, `after` (epoch seconds) and
  pagination via `page` + `per_page` (max 200 per page).
Rate limits (per Strava's published defaults, subject to change -- check
  the X-RateLimit-* response headers on your own app if in doubt):
  ~200 requests / 15 min, ~2000 requests / day.
"""
import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

TOKEN_URL = "https://www.strava.com/oauth/token"
ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "activities.db")
PER_PAGE = 200
OVERLAP_DAYS = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS activities (
    id                  INTEGER PRIMARY KEY,
    name                TEXT,
    type                TEXT,
    sport_type          TEXT,
    start_date          TEXT,       -- UTC ISO8601, from Strava's start_date
    start_date_local    TEXT,
    distance_m          REAL,
    moving_time_s        INTEGER,
    elapsed_time_s        INTEGER,
    total_elevation_gain_m REAL,
    average_speed_mps   REAL,
    max_speed_mps        REAL,
    average_heartrate   REAL,
    max_heartrate       REAL,
    average_cadence     REAL,
    suffer_score        REAL,
    workout_type        INTEGER,
    gear_id              TEXT,
    kudos_count          INTEGER,
    achievement_count    INTEGER,
    raw_json             TEXT        -- full API response for this activity, for anything not columnized above
);
CREATE TABLE IF NOT EXISTS sync_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

UPSERT_SQL = """
INSERT INTO activities (
    id, name, type, sport_type, start_date, start_date_local, distance_m,
    moving_time_s, elapsed_time_s, total_elevation_gain_m, average_speed_mps,
    max_speed_mps, average_heartrate, max_heartrate, average_cadence,
    suffer_score, workout_type, gear_id, kudos_count, achievement_count, raw_json
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(id) DO UPDATE SET
    name=excluded.name, type=excluded.type, sport_type=excluded.sport_type,
    start_date=excluded.start_date, start_date_local=excluded.start_date_local,
    distance_m=excluded.distance_m, moving_time_s=excluded.moving_time_s,
    elapsed_time_s=excluded.elapsed_time_s,
    total_elevation_gain_m=excluded.total_elevation_gain_m,
    average_speed_mps=excluded.average_speed_mps, max_speed_mps=excluded.max_speed_mps,
    average_heartrate=excluded.average_heartrate, max_heartrate=excluded.max_heartrate,
    average_cadence=excluded.average_cadence, suffer_score=excluded.suffer_score,
    workout_type=excluded.workout_type, gear_id=excluded.gear_id,
    kudos_count=excluded.kudos_count, achievement_count=excluded.achievement_count,
    raw_json=excluded.raw_json;
"""


def get_access_token(client_id, client_secret, refresh_token):
    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def fetch_activities(access_token, after_epoch=None):
    headers = {"Authorization": f"Bearer {access_token}"}
    page = 1
    while True:
        params = {"per_page": PER_PAGE, "page": page}
        if after_epoch is not None:
            params["after"] = after_epoch

        resp = requests.get(ACTIVITIES_URL, headers=headers, params=params, timeout=30)
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 60))
            print(f"Rate limited, sleeping {wait}s", file=sys.stderr)
            time.sleep(wait)
            continue
        resp.raise_for_status()

        batch = resp.json()
        if not batch:
            return
        for activity in batch:
            yield activity
        page += 1


def upsert(conn, activity):
    conn.execute(
        UPSERT_SQL,
        (
            activity["id"],
            activity.get("name"),
            activity.get("type"),
            activity.get("sport_type"),
            activity.get("start_date"),
            activity.get("start_date_local"),
            activity.get("distance"),
            activity.get("moving_time"),
            activity.get("elapsed_time"),
            activity.get("total_elevation_gain"),
            activity.get("average_speed"),
            activity.get("max_speed"),
            activity.get("average_heartrate"),
            activity.get("max_heartrate"),
            activity.get("average_cadence"),
            activity.get("suffer_score"),
            activity.get("workout_type"),
            activity.get("gear_id"),
            activity.get("kudos_count"),
            activity.get("achievement_count"),
            __import__("json").dumps(activity),
        ),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true", help="Pull entire history, ignore existing data")
    args = parser.parse_args()

    client_id = os.environ["STRAVA_CLIENT_ID"]
    client_secret = os.environ["STRAVA_CLIENT_SECRET"]
    refresh_token = os.environ["STRAVA_REFRESH_TOKEN"]

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)

    after_epoch = None
    if not args.full:
        row = conn.execute("SELECT MAX(start_date) FROM activities").fetchone()
        if row and row[0]:
            last = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
            after_epoch = int((last - timedelta(days=OVERLAP_DAYS)).timestamp())

    print(f"Mode: {'full history' if after_epoch is None else f'incremental after {after_epoch}'}")

    access_token = get_access_token(client_id, client_secret, refresh_token)

    count = 0
    for activity in fetch_activities(access_token, after_epoch):
        upsert(conn, activity)
        count += 1
    conn.commit()

    conn.execute(
        "INSERT INTO sync_meta (key, value) VALUES ('last_sync', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (datetime.now(timezone.utc).isoformat(),),
    )
    conn.commit()
    conn.close()

    print(f"Upserted {count} activities into {DB_PATH}")


if __name__ == "__main__":
    main()
