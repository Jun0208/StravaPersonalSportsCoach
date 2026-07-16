#!/usr/bin/env python3
"""
Read data/activities.db and compute this week's performance vs. historical
trend. Focused on running (the sport the athlete cares most about), with a
lightweight all-sport summary alongside it.

"Week" = Monday 00:00 to Sunday 23:59, using each activity's local start
time (start_date_local) so it lines up with the athlete's own calendar
rather than UTC.

Output: data/weekly_summary.json (latest week) -- consumed by
build_report.py for charts/cards and by the Claude Code Remote routine for
the coach narrative. Also appends the week's headline numbers to
data/weekly_history.csv so trend lines keep growing over time.
"""
import argparse
import json
import os
import sqlite3
from datetime import datetime, timedelta

import pandas as pd

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "activities.db")
SUMMARY_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "weekly_summary.json")
HISTORY_CSV = os.path.join(os.path.dirname(__file__), "..", "data", "weekly_history.csv")

RUN_TYPES = {"Run", "TrailRun", "VirtualRun"}


def load_activities():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM activities", conn)
    conn.close()
    if df.empty:
        return df
    df["start_local"] = pd.to_datetime(df["start_date_local"].str.replace("Z", "", regex=False))
    df["distance_km"] = df["distance_m"] / 1000.0
    df["moving_time_min"] = df["moving_time_s"] / 60.0
    # min/km pace, only meaningful where distance > 0
    df["pace_min_per_km"] = df["moving_time_min"] / df["distance_km"].replace(0, pd.NA)
    df["week_start"] = (df["start_local"] - pd.to_timedelta(df["start_local"].dt.weekday, unit="D")).dt.normalize()
    return df


def week_slice(df, week_start):
    return df[df["week_start"] == pd.Timestamp(week_start)]


def summarize_week(df_week, sport_filter=None):
    d = df_week[df_week["type"].isin(sport_filter)] if sport_filter else df_week
    if d.empty:
        return {
            "count": 0, "distance_km": 0.0, "moving_time_min": 0.0,
            "elevation_gain_m": 0.0, "avg_pace_min_per_km": None,
            "avg_heartrate": None,
        }
    total_distance = d["distance_km"].sum()
    total_time = d["moving_time_min"].sum()
    return {
        "count": int(len(d)),
        "distance_km": round(float(total_distance), 2),
        "moving_time_min": round(float(total_time), 1),
        "elevation_gain_m": round(float(d["total_elevation_gain_m"].sum()), 1),
        # weighted pace (total time / total distance), more meaningful than averaging per-run paces
        "avg_pace_min_per_km": round(float(total_time / total_distance), 2) if total_distance > 0 else None,
        "avg_heartrate": round(float(d["average_heartrate"].dropna().mean()), 1) if d["average_heartrate"].notna().any() else None,
        "longest_run_km": round(float(d["distance_km"].max()), 2) if len(d) else None,
        "fastest_pace_min_per_km": round(float(d["pace_min_per_km"].dropna().min()), 2) if d["pace_min_per_km"].notna().any() else None,
    }


def pct_change(new, old):
    if old in (None, 0) or new is None:
        return None
    return round((new - old) / old * 100, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--week-start",
        help="ISO date (Monday) for the week to summarize; defaults to the most recently completed Mon-Sun week.",
    )
    args = parser.parse_args()

    df = load_activities()
    if df.empty:
        raise SystemExit("No activities in data/activities.db yet -- run extract_strava.py first.")

    if args.week_start:
        target_week = datetime.fromisoformat(args.week_start).date()
    else:
        today = datetime.now().date()
        this_monday = today - timedelta(days=today.weekday())
        target_week = this_monday - timedelta(days=7)  # most recently *completed* week

    this_week = week_slice(df, target_week)
    prev_week = week_slice(df, target_week - timedelta(days=7))

    run_this = summarize_week(this_week, RUN_TYPES)
    run_prev = summarize_week(prev_week, RUN_TYPES)
    all_this = summarize_week(this_week)

    # trailing baseline: 8 completed weeks before target week, running only
    trailing_start = target_week - timedelta(weeks=8)
    trailing = df[(df["week_start"] >= pd.Timestamp(trailing_start)) & (df["week_start"] < pd.Timestamp(target_week))]
    trailing_weekly = (
        trailing[trailing["type"].isin(RUN_TYPES)]
        .groupby("week_start")
        .apply(lambda d: pd.Series({
            "distance_km": d["distance_km"].sum(),
            "moving_time_min": d["moving_time_min"].sum(),
        }))
    )
    trailing_avg_distance = float(trailing_weekly["distance_km"].mean()) if not trailing_weekly.empty else None
    trailing_avg_time = float(trailing_weekly["moving_time_min"].mean()) if not trailing_weekly.empty else None

    summary = {
        "week_start": str(target_week),
        "week_end": str(target_week + timedelta(days=6)),
        "generated_at": datetime.now().isoformat(),
        "running": run_this,
        "all_sports": all_this,
        "vs_previous_week": {
            "distance_km_pct": pct_change(run_this["distance_km"], run_prev["distance_km"]),
            "moving_time_min_pct": pct_change(run_this["moving_time_min"], run_prev["moving_time_min"]),
            "pace_min_per_km_pct": pct_change(run_this["avg_pace_min_per_km"], run_prev["avg_pace_min_per_km"]),
        },
        "vs_trailing_8wk_avg": {
            "distance_km_pct": pct_change(run_this["distance_km"], trailing_avg_distance),
            "moving_time_min_pct": pct_change(run_this["moving_time_min"], trailing_avg_time),
        },
        "trailing_8wk_avg_distance_km": round(trailing_avg_distance, 2) if trailing_avg_distance else None,
    }

    os.makedirs(os.path.dirname(SUMMARY_PATH), exist_ok=True)
    with open(SUMMARY_PATH, "w") as f:
        json.dump(summary, f, indent=2)

    # append/update this week's row in the long-running trend CSV (dedup by week_start)
    row = pd.DataFrame([{
        "week_start": str(target_week),
        "run_count": run_this["count"],
        "run_distance_km": run_this["distance_km"],
        "run_time_min": run_this["moving_time_min"],
        "run_pace_min_per_km": run_this["avg_pace_min_per_km"],
        "run_elevation_gain_m": run_this["elevation_gain_m"],
        "avg_heartrate": run_this["avg_heartrate"],
    }])
    if os.path.exists(HISTORY_CSV):
        history = pd.read_csv(HISTORY_CSV)
        history = history[history["week_start"] != str(target_week)]
        history = pd.concat([history, row], ignore_index=True)
    else:
        history = row
    history.sort_values("week_start", inplace=True)
    history.to_csv(HISTORY_CSV, index=False)

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
