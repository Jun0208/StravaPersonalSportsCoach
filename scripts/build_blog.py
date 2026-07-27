#!/usr/bin/env python3
"""
Build the public running-performance blog (docs/blog/) from the same
data/weekly_history.csv the email and dashboard use -- a separate, visual-
first presentation with no coaching narrative, styled dark/monochrome plus
one accent color.

Pages produced:
  docs/blog/index.html            -- homepage: last week, this month, this year
  docs/blog/weeks/index.html      -- archive list, newest first
  docs/blog/weeks/<week_start>.html -- one page per tracked week

Month/year bucketing: a week belongs to the calendar month/year of its
week_start. If the current calendar month has no weeks yet (e.g. the 1st-6th
before Monday's data lands), the "this month" section shows the most recent
month that does have data instead, so it's never empty.
"""
import csv
import html
import os
from datetime import date, datetime

ROOT = os.environ.get("PIPELINE_ROOT", os.path.join(os.path.dirname(__file__), ".."))
HISTORY_CSV = os.path.join(ROOT, "data", "weekly_history.csv")
BLOG_DIR = os.path.join(ROOT, "docs", "blog")
WEEKS_DIR = os.path.join(BLOG_DIR, "weeks")

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

NUM_FIELDS = ["run_count", "run_distance_km", "run_time_min", "run_pace_min_per_km", "run_elevation_gain_m"]


def load_history():
    with open(HISTORY_CSV) as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["week_start_date"] = datetime.strptime(r["week_start"], "%Y-%m-%d").date()
        for k in NUM_FIELDS:
            r[k] = float(r[k]) if r.get(k) not in (None, "") else 0.0
        r["avg_heartrate"] = float(r["avg_heartrate"]) if r.get("avg_heartrate") not in (None, "") else None
    rows.sort(key=lambda r: r["week_start_date"])
    return rows


def week_end(week_start_date):
    from datetime import timedelta
    return week_start_date + timedelta(days=6)


def fmt_pace(min_per_km):
    if not min_per_km:
        return "–"
    m = int(min_per_km)
    s = round((min_per_km - m) * 60)
    if s == 60:
        m += 1
        s = 0
    return f"{m}:{s:02d}/km"


def pct_delta(curr, prev):
    if not prev:
        return None
    return (curr - prev) / prev * 100.0


EXTREME_DELTA_PCT = 150  # beyond this, the raw % is more distracting than informative


def delta_badge(curr, prev, higher_is_up=True):
    d = pct_delta(curr, prev)
    if d is None:
        return '<span class="delta delta-flat">NEW</span>'
    arrow = "↑" if d >= 0 else "↓"
    cls = "delta-up" if d >= 0 else "delta-down"
    if abs(d) > EXTREME_DELTA_PCT:
        return f'<span class="delta {cls}">{arrow}</span>'
    return f'<span class="delta {cls}">{arrow} {abs(d):.0f}%</span>'


def month_bucket(rows, year, month):
    return [r for r in rows if r["week_start_date"].year == year and r["week_start_date"].month == month]


def find_current_month_bucket(rows, today):
    y, m = today.year, today.month
    bucket = month_bucket(rows, y, m)
    if bucket:
        return y, m, bucket
    # walk backward until a month with data is found
    for _ in range(24):
        m -= 1
        if m == 0:
            m = 12
            y -= 1
        bucket = month_bucket(rows, y, m)
        if bucket:
            return y, m, bucket
    return y, m, []


def year_bucket(rows, year):
    return [r for r in rows if r["week_start_date"].year == year]


def sum_field(rows, field):
    return sum(r[field] for r in rows)


def weighted_avg_pace(rows):
    total_time = sum_field(rows, "run_time_min")
    total_dist = sum_field(rows, "run_distance_km")
    return (total_time / total_dist) if total_dist else None


BASE_CSS = """
:root {
  --bg: #0a0a0a;
  --surface: #141414;
  --surface-2: #1c1c1c;
  --text: #ffffff;
  --text-2: #a8a8a8;
  --muted: #6e6e6e;
  --hairline: rgba(255,255,255,0.08);
  --accent: #d95926;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  -webkit-font-smoothing: antialiased;
}
a { color: inherit; text-decoration: none; }
.wrap { max-width: 880px; margin: 0 auto; padding: 0 24px; }
.nav {
  display: flex; align-items: center; justify-content: space-between;
  padding: 28px 0; border-bottom: 1px solid var(--hairline);
}
.brand {
  font-size: 15px; font-weight: 800; letter-spacing: 0.14em; text-transform: uppercase;
}
.nav-link {
  font-size: 12px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--text-2); border-bottom: 1px solid transparent;
}
.nav-link:hover { color: var(--text); border-color: var(--text); }
.section { padding: 48px 0; border-bottom: 1px solid var(--hairline); }
.section:last-of-type { border-bottom: none; }
.eyebrow {
  font-size: 11px; font-weight: 700; letter-spacing: 0.18em; text-transform: uppercase;
  color: var(--accent); margin: 0 0 10px;
}
.section-title {
  font-size: 28px; font-weight: 800; letter-spacing: -0.01em; margin: 0 0 28px;
  text-transform: uppercase;
}
.stat-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 1px; background: var(--hairline); border: 1px solid var(--hairline);
}
.stat-tile { background: var(--surface); padding: 20px 18px; }
.stat-label {
  font-size: 10px; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase;
  color: var(--muted); margin: 0 0 8px;
}
.stat-value {
  font-size: 30px; font-weight: 800; letter-spacing: -0.02em; line-height: 1.1;
  font-variant-numeric: proportional-nums;
}
.stat-unit { font-size: 14px; font-weight: 600; color: var(--text-2); margin-left: 4px; }
.delta { display: inline-block; margin-top: 8px; font-size: 12px; font-weight: 700; }
.delta-up { color: var(--text); }
.delta-down { color: var(--text-2); }
.delta-flat { color: var(--muted); }
.date-range { font-size: 14px; color: var(--text-2); margin: 0 0 6px; }
.hero-row { display: flex; gap: 48px; flex-wrap: wrap; margin-bottom: 32px; }
.hero-stat .stat-value { font-size: 44px; }
.chart-wrap { margin-top: 8px; }
.bar-row { display: flex; align-items: flex-end; gap: 6px; height: 140px; }
.bar-col { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; height: 100%; }
.bar { width: 100%; background: var(--accent); border-radius: 3px 3px 0 0; min-height: 2px; }
.bar-col.empty .bar { background: var(--surface-2); }
.bar-col.muted .bar { background: #3a3a3a; }
.bar-label { font-size: 10px; color: var(--muted); margin-top: 8px; letter-spacing: 0.04em; text-transform: uppercase; }
.bar-value { font-size: 10px; color: var(--text-2); margin-bottom: 4px; font-weight: 600; }
footer { padding: 32px 0 48px; }
.footer-text { font-size: 12px; color: var(--muted); }
.week-list { border-top: 1px solid var(--hairline); }
.week-row {
  display: flex; align-items: center; justify-content: space-between;
  padding: 20px 0; border-bottom: 1px solid var(--hairline);
}
.week-row:hover .week-date { color: var(--accent); }
.week-date { font-size: 16px; font-weight: 700; transition: color 0.15s; }
.week-stats { display: flex; gap: 24px; font-size: 13px; color: var(--text-2); }
.week-stats b { color: var(--text); font-weight: 700; }
.back-link {
  display: inline-block; margin: 28px 0 4px; font-size: 12px; font-weight: 700;
  letter-spacing: 0.08em; text-transform: uppercase; color: var(--text-2);
}
.back-link:hover { color: var(--text); }
.week-nav {
  display: flex; justify-content: space-between; padding: 32px 0 48px;
  border-top: 1px solid var(--hairline); margin-top: 16px;
}
.week-nav-btn {
  font-size: 12px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--text-2); padding: 10px 16px; border: 1px solid var(--hairline);
}
.week-nav-btn:hover { color: var(--text); border-color: var(--text-2); }
.week-nav-btn.disabled { opacity: 0.3; pointer-events: none; }
@media (max-width: 520px) {
  .section-title { font-size: 22px; }
  .stat-value { font-size: 24px; }
  .hero-stat .stat-value { font-size: 32px; }
  .week-stats { display: none; }
}
"""


def page_shell(title, body):
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>{BASE_CSS}</style>
</head>
<body>
{body}
</body>
</html>
"""


def nav_html(depth=0):
    """depth = number of directories below docs/blog/ this page lives in
    (0 for index.html, 1 for weeks/*.html) -- controls relative path prefixes."""
    prefix = "../" * depth
    return f"""<div class="wrap"><div class="nav">
  <a class="brand" href="{prefix}index.html">Running Log</a>
  <a class="nav-link" href="{prefix}weeks/index.html">All Weeks</a>
</div></div>"""


def stat_tiles(distance, time_min, pace, elevation, hr, deltas=None):
    deltas = deltas or {}
    hours = int(time_min // 60)
    mins = int(round(time_min % 60))
    time_str = f"{hours}h {mins:02d}m" if hours else f"{mins}m"
    tiles = [
        ("Distance", f"{distance:.1f}", "km", deltas.get("distance")),
        ("Time", time_str, "", deltas.get("time")),
        ("Pace", fmt_pace(pace), "", deltas.get("pace")),
        ("Elevation", f"{elevation:.0f}", "m", deltas.get("elevation")),
    ]
    if hr:
        tiles.append(("Avg HR", f"{hr:.0f}", "bpm", None))
    out = ['<div class="stat-grid">']
    for label, value, unit, delta in tiles:
        unit_html = f'<span class="stat-unit">{unit}</span>' if unit else ""
        delta_html = delta if delta else ""
        out.append(
            f'<div class="stat-tile"><p class="stat-label">{label}</p>'
            f'<div class="stat-value">{value}{unit_html}</div>{delta_html}</div>'
        )
    out.append("</div>")
    return "".join(out)


def build_homepage(rows, today):
    latest = rows[-1]
    prev = rows[-2] if len(rows) > 1 else None

    deltas = {}
    if prev:
        deltas["distance"] = delta_badge(latest["run_distance_km"], prev["run_distance_km"])
        deltas["time"] = delta_badge(latest["run_time_min"], prev["run_time_min"])
        if latest["run_pace_min_per_km"] and prev["run_pace_min_per_km"]:
            deltas["pace"] = delta_badge(latest["run_pace_min_per_km"], prev["run_pace_min_per_km"])
        deltas["elevation"] = delta_badge(latest["run_elevation_gain_m"], prev["run_elevation_gain_m"])

    we = week_end(latest["week_start_date"])
    date_range = f"{latest['week_start_date'].strftime('%b %d')}–{we.strftime('%b %d, %Y')}"

    section1 = f"""
    <section class="section">
      <p class="eyebrow">Last Week</p>
      <h2 class="section-title">{date_range}</h2>
      {stat_tiles(latest["run_distance_km"], latest["run_time_min"], latest["run_pace_min_per_km"],
                   latest["run_elevation_gain_m"], latest["avg_heartrate"], deltas)}
    </section>"""

    my, mm, month_rows = find_current_month_bucket(rows, today)
    month_dist = sum_field(month_rows, "run_distance_km")
    month_time = sum_field(month_rows, "run_time_min")
    month_runs = int(sum_field(month_rows, "run_count"))
    month_pace = weighted_avg_pace(month_rows)
    month_elev = sum_field(month_rows, "run_elevation_gain_m")
    label = MONTH_NAMES[mm - 1] + (f" {my}" if my != today.year else "")

    section2 = f"""
    <section class="section">
      <p class="eyebrow">{label}</p>
      <h2 class="section-title">{month_runs} Run{"s" if month_runs != 1 else ""}</h2>
      {stat_tiles(month_dist, month_time, month_pace, month_elev, None)}
    </section>"""

    yr_rows = year_bucket(rows, today.year)
    yr_dist = sum_field(yr_rows, "run_distance_km")
    yr_time = sum_field(yr_rows, "run_time_min")
    yr_hours = int(yr_time // 60)

    monthly_dist = [0.0] * 12
    for r in yr_rows:
        monthly_dist[r["week_start_date"].month - 1] += r["run_distance_km"]
    max_month = max(monthly_dist) or 1.0
    bars = []
    for i, d in enumerate(monthly_dist):
        h = int((d / max_month) * 120) if d else 0
        empty_cls = " empty" if d == 0 else ""
        val_label = f"{d:.0f}" if d else ""
        bars.append(
            f'<div class="bar-col{empty_cls}"><span class="bar-value">{val_label}</span>'
            f'<div class="bar" style="height:{max(h,2)}px"></div>'
            f'<span class="bar-label">{MONTH_NAMES[i][:3]}</span></div>'
        )

    section3 = f"""
    <section class="section">
      <p class="eyebrow">{today.year} Year To Date</p>
      <h2 class="section-title">Season So Far</h2>
      <div class="hero-row">
        <div class="hero-stat"><p class="stat-label">Total Distance</p>
          <div class="stat-value">{yr_dist:.0f}<span class="stat-unit">km</span></div></div>
        <div class="hero-stat"><p class="stat-label">Total Time</p>
          <div class="stat-value">{yr_hours}<span class="stat-unit">hours</span></div></div>
      </div>
      <p class="stat-label" style="margin-bottom:12px;">Monthly Distance (km)</p>
      <div class="chart-wrap"><div class="bar-row">{"".join(bars)}</div></div>
    </section>"""

    footer = f"""<footer class="wrap"><p class="footer-text">Updated weekly, sourced from Strava. Last refreshed {today.strftime('%B %d, %Y')}.</p></footer>"""

    body = nav_html(depth=0) + f'<div class="wrap">{section1}{section2}{section3}</div>' + footer
    return page_shell("Running Log", body)


def build_week_archive_list(rows):
    items = []
    for r in reversed(rows):
        we = week_end(r["week_start_date"])
        date_range = f"{r['week_start_date'].strftime('%b %d')}–{we.strftime('%b %d, %Y')}"
        items.append(f"""
        <a class="week-row" href="{r['week_start']}.html">
          <span class="week-date">{date_range}</span>
          <span class="week-stats"><span><b>{r['run_distance_km']:.1f}</b> km</span>
            <span><b>{fmt_pace(r['run_pace_min_per_km'])}</b></span>
            <span><b>{int(r['run_count'])}</b> run{"s" if r['run_count'] != 1 else ""}</span></span>
        </a>""")

    body = nav_html(depth=1) + f"""<div class="wrap">
      <section class="section" style="border-bottom:none;">
        <p class="eyebrow">Archive</p>
        <h2 class="section-title">All Weeks</h2>
        <div class="week-list">{"".join(items)}</div>
      </section>
    </div>"""
    return page_shell("All Weeks — Running Log", body)


def trend_chart_html(rows, idx, window=8):
    """Bar chart of distance for up to `window` weeks ending at idx, with
    the current week's bar in the accent color and the rest muted -- gives
    each week page context for where that week sits in the recent trend."""
    start = max(0, idx - window + 1)
    span = rows[start:idx + 1]
    max_dist = max((r["run_distance_km"] for r in span), default=0) or 1.0
    bars = []
    for i, r in enumerate(span):
        d = r["run_distance_km"]
        h = int((d / max_dist) * 120) if d else 0
        is_current = (start + i) == idx
        cls = "" if is_current else " muted"
        if d == 0:
            cls = " empty"
        val_label = f"{d:.0f}" if d else ""
        wk_label = r["week_start_date"].strftime("%-m/%-d") if os.name != "nt" else r["week_start_date"].strftime("%m/%d")
        bars.append(
            f'<div class="bar-col{cls}"><span class="bar-value">{val_label}</span>'
            f'<div class="bar" style="height:{max(h,2)}px"></div>'
            f'<span class="bar-label">{wk_label}</span></div>'
        )
    return f"""
      <section class="section" style="border-bottom:none; padding-top:0;">
        <p class="stat-label" style="margin-bottom:12px;">Recent Trend — Distance (km)</p>
        <div class="chart-wrap"><div class="bar-row">{"".join(bars)}</div></div>
      </section>"""


def build_week_page(rows, idx):
    r = rows[idx]
    prev = rows[idx - 1] if idx > 0 else None
    nxt = rows[idx + 1] if idx < len(rows) - 1 else None

    deltas = {}
    if prev:
        deltas["distance"] = delta_badge(r["run_distance_km"], prev["run_distance_km"])
        deltas["time"] = delta_badge(r["run_time_min"], prev["run_time_min"])
        if r["run_pace_min_per_km"] and prev["run_pace_min_per_km"]:
            deltas["pace"] = delta_badge(r["run_pace_min_per_km"], prev["run_pace_min_per_km"])
        deltas["elevation"] = delta_badge(r["run_elevation_gain_m"], prev["run_elevation_gain_m"])

    we = week_end(r["week_start_date"])
    date_range = f"{r['week_start_date'].strftime('%b %d')}–{we.strftime('%b %d, %Y')}"

    prev_btn = (f'<a class="week-nav-btn" href="{prev["week_start"]}.html">← Previous Week</a>'
                if prev else '<span class="week-nav-btn disabled">← Previous Week</span>')
    next_btn = (f'<a class="week-nav-btn" href="{nxt["week_start"]}.html">Next Week →</a>'
                if nxt else '<span class="week-nav-btn disabled">Next Week →</span>')

    body = nav_html(depth=1) + f"""<div class="wrap">
      <a class="back-link" href="index.html">← All Weeks</a>
      <section class="section" style="border-bottom:none;">
        <p class="eyebrow">Week</p>
        <h2 class="section-title">{date_range}</h2>
        {stat_tiles(r["run_distance_km"], r["run_time_min"], r["run_pace_min_per_km"],
                     r["run_elevation_gain_m"], r["avg_heartrate"], deltas)}
      </section>
      {trend_chart_html(rows, idx)}
      <div class="week-nav">{prev_btn}{next_btn}</div>
    </div>"""
    return page_shell(f"{date_range} — Running Log", body)


def main():
    rows = load_history()
    if not rows:
        print("No history data, skipping blog build.")
        return

    os.makedirs(WEEKS_DIR, exist_ok=True)
    today = date.today()

    with open(os.path.join(BLOG_DIR, "index.html"), "w") as f:
        f.write(build_homepage(rows, today))

    with open(os.path.join(WEEKS_DIR, "index.html"), "w") as f:
        f.write(build_week_archive_list(rows))

    for i, r in enumerate(rows):
        with open(os.path.join(WEEKS_DIR, f"{r['week_start']}.html"), "w") as f:
            f.write(build_week_page(rows, i))

    print(f"Wrote {BLOG_DIR}/index.html, weeks/index.html, and {len(rows)} week pages.")


if __name__ == "__main__":
    main()
