#!/usr/bin/env python3
"""
Turn data/weekly_summary.json + data/weekly_history.csv into the static
dashboard published via GitHub Pages: docs/index.html (latest week) and an
archived docs/reports/<week_start>.html snapshot.

Charts are hand-built inline SVG (no JS framework, no external assets --
GitHub Pages and email clients both need to render this reliably). Colors
and mark specs follow the project's dataviz skill: one hue per series,
thin 2px lines with rounded ends, hairline gridlines, muted axis ink,
direct labels on the current point only (not every point), a plain-text
table under each chart as the accessible fallback, and light/dark mode via
prefers-color-scheme using the validated default palette
(see references/palette.md in the dataviz skill).

If data/coach_narrative.md exists (written by the weekly Claude Code
Remote routine), its content is embedded into the page under "This week
with your coach". If not, that section is left as a placeholder --
build_report.py runs before the narrative step in the pipeline.
"""
import csv
import html
import json
import os
import re
from datetime import datetime

ROOT = os.path.join(os.path.dirname(__file__), "..")
SUMMARY_PATH = os.path.join(ROOT, "data", "weekly_summary.json")
HISTORY_CSV = os.path.join(ROOT, "data", "weekly_history.csv")
NARRATIVE_PATH = os.path.join(ROOT, "data", "coach_narrative.md")
DOCS_DIR = os.path.join(ROOT, "docs")
REPORTS_DIR = os.path.join(DOCS_DIR, "reports")

STYLE = """
:root {
  color-scheme: light;
  --surface-1:      #fcfcfb;
  --page:           #f9f9f7;
  --text-primary:   #0b0b0b;
  --text-secondary: #52514e;
  --muted:          #898781;
  --grid:           #e1e0d9;
  --baseline:       #c3c2b7;
  --series-1:       #2a78d6;
  --series-2:       #1baf7a;
  --good:           #006300;
  --border:         rgba(11,11,11,0.10);
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --surface-1:      #1a1a19;
    --page:           #0d0d0d;
    --text-primary:   #ffffff;
    --text-secondary: #c3c2b7;
    --muted:          #898781;
    --grid:           #2c2c2a;
    --baseline:       #383835;
    --series-1:       #3987e5;
    --series-2:       #199e70;
    --good:           #0ca30c;
    --border:         rgba(255,255,255,0.10);
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --surface-1:      #1a1a19;
  --page:           #0d0d0d;
  --text-primary:   #ffffff;
  --text-secondary: #c3c2b7;
  --muted:          #898781;
  --grid:           #2c2c2a;
  --baseline:       #383835;
  --series-1:       #3987e5;
  --series-2:       #199e70;
  --good:           #0ca30c;
  --border:         rgba(255,255,255,0.10);
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 32px 16px 64px;
  background: var(--page); color: var(--text-primary);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
}
.wrap { max-width: 880px; margin: 0 auto; }
h1 { font-size: 1.5rem; margin-bottom: 4px; }
.subtitle { color: var(--text-secondary); margin-bottom: 28px; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 32px; }
.card {
  background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px;
  padding: 16px;
}
.card .label { color: var(--muted); font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.04em; }
.card .value { font-size: 1.6rem; font-weight: 600; margin: 4px 0; }
.card .delta { font-size: 0.85rem; color: var(--text-secondary); }
.card .delta.good { color: var(--good); }
.panel {
  background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px;
  padding: 20px; margin-bottom: 24px;
}
.panel h2 { font-size: 1.05rem; margin: 0 0 12px; }
table { width: 100%; border-collapse: collapse; font-size: 0.82rem; margin-top: 12px; color: var(--text-secondary); }
th, td { text-align: right; padding: 4px 6px; border-bottom: 1px solid var(--grid); font-variant-numeric: tabular-nums; }
th:first-child, td:first-child { text-align: left; }
.narrative { line-height: 1.6; }
.narrative p { margin: 0 0 12px; }
.narrative ul { margin: 0 0 12px; padding-left: 20px; }
.narrative li { margin-bottom: 4px; }
.narrative.placeholder { color: var(--muted); font-style: italic; }
footer { color: var(--muted); font-size: 0.8rem; margin-top: 24px; }
a { color: var(--series-1); }
"""


def inline_md(text):
    escaped = html.escape(text)
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)


def render_narrative(text):
    """Minimal markdown -> HTML: paragraphs, **bold**, and '- ' bullet lists.
    The dashboard/email render this as raw preformatted text otherwise, so
    the coach narrative's markdown (bold headers, bullet training plan)
    would show up as literal asterisks and dashes instead of formatting."""
    if not text:
        return None
    paragraphs = re.split(r"\n\s*\n", text.strip())
    parts = []
    for para in paragraphs:
        lines = [l.strip() for l in para.split("\n") if l.strip()]
        if lines and all(l.startswith(("- ", "* ")) for l in lines):
            items = "".join(f"<li>{inline_md(l[2:])}</li>" for l in lines)
            parts.append(f"<ul>{items}</ul>")
        else:
            parts.append(f"<p>{inline_md(' '.join(lines))}</p>")
    return "".join(parts)


def load_summary():
    with open(SUMMARY_PATH) as f:
        return json.load(f)


def load_history():
    rows = []
    if os.path.exists(HISTORY_CSV):
        with open(HISTORY_CSV) as f:
            rows = list(csv.DictReader(f))
    return rows[-12:]  # last 12 weeks


def svg_bar_chart(rows, key, unit, color_var="--series-1", height=180, width=780):
    values = [float(r[key]) if r[key] not in ("", None) else 0.0 for r in rows]
    labels = [r["week_start"][5:] for r in rows]  # MM-DD
    if not values:
        return "<p>No history yet.</p>"
    max_v = max(values) or 1
    n = len(values)
    pad_l, pad_r, pad_t, pad_b = 8, 8, 16, 24
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    bar_w = plot_w / n * 0.6
    gap = plot_w / n

    bars = []
    for i, v in enumerate(values):
        x = pad_l + i * gap + (gap - bar_w) / 2
        bar_h = (v / max_v) * plot_h
        y = pad_t + (plot_h - bar_h)
        is_last = i == n - 1
        title = f"{labels[i]}: {v:.1f} {unit}"
        bars.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{max(bar_h,1):.1f}" '
            f'rx="4" fill="var({color_var})" opacity="{1.0 if is_last else 0.55}">'
            f"<title>{title}</title></rect>"
        )
        if is_last:
            bars.append(
                f'<text x="{x + bar_w/2:.1f}" y="{y - 6:.1f}" text-anchor="middle" '
                f'font-size="11" fill="var(--text-primary)">{v:.1f}</text>'
            )

    tick_labels = "".join(
        f'<text x="{pad_l + i*gap + gap/2:.1f}" y="{height-6}" text-anchor="middle" '
        f'font-size="9" fill="var(--muted)">{labels[i] if i % 2 == 0 else ""}</text>'
        for i in range(n)
    )
    baseline = f'<line x1="{pad_l}" y1="{pad_t+plot_h}" x2="{width-pad_r}" y2="{pad_t+plot_h}" stroke="var(--baseline)" stroke-width="1"/>'

    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" role="img" '
        f'aria-label="Weekly {key} bar chart">{"".join(bars)}{baseline}{tick_labels}</svg>'
    )


def svg_line_chart(rows, key, unit, color_var="--series-2", height=180, width=780):
    pairs = [(r["week_start"][5:], float(r[key])) for r in rows if r.get(key) not in ("", None, "None")]
    if len(pairs) < 2:
        return "<p>Not enough history yet for a trend line.</p>"
    labels = [p[0] for p in pairs]
    values = [p[1] for p in pairs]
    n = len(values)
    pad_l, pad_r, pad_t, pad_b = 8, 40, 16, 24
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    min_v, max_v = min(values), max(values)
    span = (max_v - min_v) or 1
    step = plot_w / (n - 1)

    def xy(i):
        x = pad_l + i * step
        y = pad_t + plot_h - ((values[i] - min_v) / span) * plot_h
        return x, y

    points = [xy(i) for i in range(n)]
    path_d = " ".join(f"{'M' if i==0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(points))
    dots = []
    for i, (x, y) in enumerate(points):
        is_last = i == n - 1
        dots.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{4 if is_last else 3}" fill="var({color_var})">'
            f"<title>{labels[i]}: {values[i]:.2f} {unit}</title></circle>"
        )
    dots.append(
        f'<text x="{points[-1][0]+8:.1f}" y="{points[-1][1]+4:.1f}" font-size="11" '
        f'fill="var(--text-primary)">{values[-1]:.2f}</text>'
    )
    tick_labels = "".join(
        f'<text x="{pad_l + i*step:.1f}" y="{height-6}" text-anchor="middle" '
        f'font-size="9" fill="var(--muted)">{labels[i] if i % 2 == 0 else ""}</text>'
        for i in range(n)
    )
    baseline = f'<line x1="{pad_l}" y1="{pad_t+plot_h}" x2="{width-pad_r}" y2="{pad_t+plot_h}" stroke="var(--baseline)" stroke-width="1"/>'

    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" role="img" '
        f'aria-label="Weekly {key} trend line">'
        f'<path d="{path_d}" fill="none" stroke="var({color_var})" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round"/>{"".join(dots)}{baseline}{tick_labels}</svg>'
    )


def history_table(rows):
    head = "<tr><th>Week</th><th>Runs</th><th>Distance (km)</th><th>Time (min)</th><th>Pace (min/km)</th></tr>"
    body = "".join(
        f'<tr><td>{r["week_start"]}</td><td>{r["run_count"]}</td>'
        f'<td>{r["run_distance_km"]}</td><td>{r["run_time_min"]}</td><td>{r["run_pace_min_per_km"]}</td></tr>'
        for r in rows
    )
    return f"<table>{head}{body}</table>"


def stat_card(label, value, delta=None):
    delta_html = ""
    if delta is not None:
        cls = "good" if delta > 0 else ""
        arrow = "▲" if delta > 0 else ("▼" if delta < 0 else "→")
        delta_html = f'<div class="delta {cls}">{arrow} {abs(delta):.1f}% vs previous week</div>'
    return f'<div class="card"><div class="label">{label}</div><div class="value">{value}</div>{delta_html}</div>'


def render_page(summary, history, narrative, is_archive=False):
    run = summary["running"]
    vs_prev = summary["vs_previous_week"]
    cards = "".join([
        stat_card("Runs", run["count"]),
        stat_card("Distance", f'{run["distance_km"]} km', vs_prev.get("distance_km_pct")),
        stat_card("Moving time", f'{run["moving_time_min"]:.0f} min', vs_prev.get("moving_time_min_pct")),
        stat_card("Avg pace", f'{run["avg_pace_min_per_km"]} min/km' if run["avg_pace_min_per_km"] else "-"),
        stat_card("Elevation gain", f'{run["elevation_gain_m"]:.0f} m'),
        stat_card("Avg heart rate", f'{run["avg_heartrate"]} bpm' if run["avg_heartrate"] else "-"),
    ])

    lifetime = summary.get("all_time")
    lifetime_html = ""
    if lifetime:
        vs_lifetime = summary.get("vs_all_time_avg", {}).get("distance_km_pct")
        lifetime_cards = "".join([
            stat_card("Weeks tracked", lifetime["weeks_tracked"]),
            stat_card("Distance this week vs. your average", f'{run["distance_km"]} / {lifetime["avg_weekly_distance_km"]} km', vs_lifetime),
            stat_card("Best week ever", f'{lifetime["best_week_distance_km"]} km', None),
            stat_card("Total distance logged", f'{lifetime["total_distance_km"]:.0f} km'),
        ])
        lifetime_html = f"""
  <div class="panel">
    <h2>Since you started tracking</h2>
    <div class="cards">{lifetime_cards}</div>
  </div>"""

    narrative_html = (
        f'<div class="narrative">{render_narrative(narrative)}</div>' if narrative
        else '<div class="narrative placeholder">Coach narrative for this week hasn\'t been generated yet.</div>'
    )

    home_link = "" if is_archive else ""
    back_link = '<p><a href="../index.html">&larr; Back to latest</a></p>' if is_archive else ""

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Athlete Coach — Week of {summary['week_start']}</title>
<style>{STYLE}</style>
</head>
<body>
<div class="wrap">
  {back_link}
  <h1>Weekly Athlete Report</h1>
  <div class="subtitle">Week of {summary['week_start']} to {summary['week_end']} · generated {summary['generated_at'][:16].replace('T',' ')}</div>

  <div class="cards">{cards}</div>
  {lifetime_html}
  <div class="panel">
    <h2>This week with your coach</h2>
    {narrative_html}
  </div>

  <div class="panel">
    <h2>Weekly running distance (last {len(history)} weeks)</h2>
    {svg_bar_chart(history, "run_distance_km", "km", "--series-1")}
    {history_table(history)}
  </div>

  <div class="panel">
    <h2>Weekly average pace (last {len(history)} weeks)</h2>
    {svg_line_chart(history, "run_pace_min_per_km", "min/km", "--series-2")}
  </div>

  <footer>Data source: Strava API. Extracted and analyzed automatically every Monday.</footer>
</div>
</body>
</html>"""


def main():
    summary = load_summary()
    history = load_history()
    narrative = None
    if os.path.exists(NARRATIVE_PATH):
        with open(NARRATIVE_PATH) as f:
            narrative = f.read().strip()

    os.makedirs(REPORTS_DIR, exist_ok=True)

    index_html = render_page(summary, history, narrative, is_archive=False)
    with open(os.path.join(DOCS_DIR, "index.html"), "w") as f:
        f.write(index_html)

    archive_html = render_page(summary, history, narrative, is_archive=True)
    archive_path = os.path.join(REPORTS_DIR, f"{summary['week_start']}.html")
    with open(archive_path, "w") as f:
        f.write(archive_html)

    print(f"Wrote {os.path.join(DOCS_DIR, 'index.html')} and {archive_path}")


if __name__ == "__main__":
    main()
