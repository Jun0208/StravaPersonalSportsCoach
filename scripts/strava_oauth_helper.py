#!/usr/bin/env python3
"""
One-time, run-it-yourself helper to get a Strava refresh token.

Why this exists: the automated pipeline (GitHub Actions) needs a Strava
*refresh token* to mint access tokens on every run without you clicking
"authorize" again. Strava only hands out a refresh token through an
interactive OAuth consent screen in a browser, so that first step can't be
automated -- you do it once, here, and the resulting refresh token then
lives as a GitHub Actions secret forever (Strava refresh tokens don't
expire unless you revoke access).

Run this on your own machine (NOT in this sandboxed session -- it has no
network route to strava.com). Requires: pip install requests

Usage:
    python3 scripts/strava_oauth_helper.py --client-id 12345 --client-secret abc123...

Docs this follows: https://developers.strava.com/docs/authentication/
"""
import argparse
import sys
import urllib.parse

import requests

AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/oauth/token"
# activity:read_all is required to see private activities, not just public ones.
SCOPE = "read,activity:read_all"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-id", required=True, help="From strava.com/settings/api")
    parser.add_argument("--client-secret", required=True, help="From strava.com/settings/api")
    parser.add_argument(
        "--redirect-uri",
        default="http://localhost/exchange_token",
        help="Must match a domain you registered as 'Authorization Callback Domain' "
        "in your Strava API app settings (default assumes you registered 'localhost').",
    )
    args = parser.parse_args()

    params = {
        "client_id": args.client_id,
        "redirect_uri": args.redirect_uri,
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": SCOPE,
    }
    auth_url = f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"

    print("Step 1: Open this URL in your browser and click 'Authorize':\n")
    print(f"  {auth_url}\n")
    print(
        "Step 2: Strava will redirect you to a URL that starts with your "
        f"redirect-uri ({args.redirect_uri}) and 404s in your browser -- that's "
        "expected, just copy the FULL resulting URL from the address bar (it "
        "contains ?code=... in the query string).\n"
    )
    pasted = input("Paste the full redirect URL (or just the code value) here: ").strip()

    if "code=" in pasted:
        code = urllib.parse.parse_qs(urllib.parse.urlparse(pasted).query)["code"][0]
    else:
        code = pasted

    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": args.client_id,
            "client_secret": args.client_secret,
            "code": code,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"Token exchange failed ({resp.status_code}): {resp.text}", file=sys.stderr)
        sys.exit(1)

    payload = resp.json()
    print("\nSuccess. Add these as GitHub Actions repository secrets "
          "(Settings -> Secrets and variables -> Actions -> New repository secret):\n")
    print(f"  STRAVA_CLIENT_ID       = {args.client_id}")
    print(f"  STRAVA_CLIENT_SECRET   = {args.client_secret}")
    print(f"  STRAVA_REFRESH_TOKEN   = {payload['refresh_token']}")
    print(
        "\nDo not commit these anywhere. The refresh token above is a live "
        "credential to your Strava account's activity data."
    )


if __name__ == "__main__":
    main()
