#!/usr/bin/env python3
"""
Send the weekly report email via Gmail SMTP.

Requires env vars:
  GMAIL_ADDRESS       - the Gmail account to send from
  GMAIL_APP_PASSWORD  - an App Password (not your normal Gmail password),
                        generated at https://myaccount.google.com/apppasswords
                        after enabling 2-Step Verification
  RECIPIENT_EMAIL     - where to send the report (can be the same address)
  PAGES_URL           - link to the full dashboard, e.g.
                        https://<owner>.github.io/<repo>/

Reads data/weekly_summary.json and data/coach_narrative.md (written by the
Claude Code Remote weekly routine) to build the email body. Keeps the email
itself simple (stat table + narrative text + a link to the full interactive
dashboard) since HTML/CSS support varies wildly across email clients --
the rich charts live on the GitHub Pages site, not in the inbox.
"""
import html
import json
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

ROOT = os.path.join(os.path.dirname(__file__), "..")
SUMMARY_PATH = os.path.join(ROOT, "data", "weekly_summary.json")
NARRATIVE_PATH = os.path.join(ROOT, "data", "coach_narrative.md")


def inline_md(text):
    escaped = html.escape(text)
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)


def narrative_to_html(text):
    """Same minimal markdown -> HTML as build_report.py's render_narrative --
    duplicated rather than shared since these are independent scripts, but
    the email body would otherwise show literal '**' and '-' characters."""
    if not text:
        return ""
    paragraphs = re.split(r"\n\s*\n", text.strip())
    parts = []
    for para in paragraphs:
        lines = [l.strip() for l in para.split("\n") if l.strip()]
        if lines and all(l.startswith(("- ", "* ")) for l in lines):
            items = "".join(f"<li>{inline_md(l[2:])}</li>" for l in lines)
            parts.append(f'<ul style="margin:0 0 12px; padding-left:20px;">{items}</ul>')
        else:
            parts.append(f'<p style="margin:0 0 12px;">{inline_md(" ".join(lines))}</p>')
    return "".join(parts)


def strip_md(text):
    """Strip markdown bold markers for the plain-text email body."""
    return re.sub(r"\*\*(.+?)\*\*", r"\1", text)


def main():
    with open(SUMMARY_PATH) as f:
        summary = json.load(f)

    narrative = ""
    if os.path.exists(NARRATIVE_PATH):
        with open(NARRATIVE_PATH) as f:
            narrative = f.read().strip()

    run = summary["running"]
    pages_url = os.environ.get("PAGES_URL", "").rstrip("/")
    report_url = f"{pages_url}/reports/{summary['week_start']}.html" if pages_url else None

    subject = f"Your week of {summary['week_start']}: {run['distance_km']} km, {run['count']} runs"

    text_lines = [
        f"Weekly Athlete Report -- {summary['week_start']} to {summary['week_end']}",
        "",
        f"Runs: {run['count']}",
        f"Distance: {run['distance_km']} km",
        f"Moving time: {run['moving_time_min']:.0f} min",
        f"Avg pace: {run['avg_pace_min_per_km']} min/km" if run["avg_pace_min_per_km"] else "Avg pace: -",
        f"Elevation gain: {run['elevation_gain_m']:.0f} m",
        "",
        strip_md(narrative) if narrative else "(Coach narrative unavailable this week.)",
    ]
    if report_url:
        text_lines += ["", f"Full dashboard with charts: {report_url}"]
    text_body = "\n".join(text_lines)

    html_body = f"""
    <div style="font-family: system-ui, -apple-system, sans-serif; max-width:600px; margin:0 auto;">
      <h2>Weekly Athlete Report</h2>
      <p style="color:#666;">{summary['week_start']} to {summary['week_end']}</p>
      <table style="width:100%; border-collapse:collapse; margin-bottom:20px;">
        <tr><td style="padding:4px 0;">Runs</td><td style="text-align:right;"><b>{run['count']}</b></td></tr>
        <tr><td style="padding:4px 0;">Distance</td><td style="text-align:right;"><b>{run['distance_km']} km</b></td></tr>
        <tr><td style="padding:4px 0;">Moving time</td><td style="text-align:right;"><b>{run['moving_time_min']:.0f} min</b></td></tr>
        <tr><td style="padding:4px 0;">Avg pace</td><td style="text-align:right;"><b>{run['avg_pace_min_per_km'] or '-'} min/km</b></td></tr>
        <tr><td style="padding:4px 0;">Elevation gain</td><td style="text-align:right;"><b>{run['elevation_gain_m']:.0f} m</b></td></tr>
      </table>
      <div style="line-height:1.5;">{narrative_to_html(narrative) if narrative else "(Coach narrative unavailable this week.)"}</div>
      {f'<p style="margin-top:20px;"><a href="{report_url}">View the full dashboard &rarr;</a></p>' if report_url else ''}
    </div>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = os.environ["GMAIL_ADDRESS"]
    msg["To"] = os.environ["RECIPIENT_EMAIL"]
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"])
        server.send_message(msg)

    print(f"Sent report email to {os.environ['RECIPIENT_EMAIL']}")


if __name__ == "__main__":
    main()
