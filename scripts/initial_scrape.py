#!/usr/bin/env python3
"""
initial_scrape.py - GitHub Search API로 @claude 계정의 일별 커밋 수를 수집.

시작일(2024-01-01)부터 어제까지 모든 날짜에 대해 커밋 수를 가져온다.
체크포인트 저장, 중단 후 재개, failed_dates 재시도를 지원한다.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR.parent / "data"
DATA_FILE = DATA_DIR / "contributions.json"

USERNAME = "claude"
USER_ID = 81847
START_DATE = "2024-01-01"
REQUEST_INTERVAL = 2.2  # seconds between requests
CHECKPOINT_EVERY = 25
COOLDOWN_EVERY = 150
COOLDOWN_SECONDS = 60
MAX_RETRIES = 3


def get_token():
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    print("Error: No GitHub token found. Set GITHUB_TOKEN or install gh CLI.", file=sys.stderr)
    sys.exit(1)


def load_data():
    if DATA_FILE.exists():
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {
        "last_updated": None,
        "metadata": {
            "username": USERNAME,
            "user_id": USER_ID,
            "scrape_start_date": START_DATE,
            "total_commits": 0,
        },
        "contributions": {},
        "failed_dates": [],
    }


def save_data(data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data["metadata"]["total_commits"] = sum(data["contributions"].values())
    tmp_fd, tmp_path = tempfile.mkstemp(dir=DATA_DIR, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp_path, DATA_FILE)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def fetch_commit_count(date_str, token):
    url = (
        f"https://api.github.com/search/commits"
        f"?q=author:{USERNAME}+author-date:{date_str}"
        f"&per_page=1"
    )
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("User-Agent", "the-claude-index-scraper")

    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode())
                return body.get("total_count", 0)
        except urllib.error.HTTPError as e:
            if e.code == 403:
                reset_ts = e.headers.get("X-Ratelimit-Reset")
                if reset_ts:
                    wait = max(int(reset_ts) - int(time.time()), 1)
                    print(f"  Rate limited (403). Waiting {wait}s...")
                    time.sleep(wait + 1)
                else:
                    time.sleep(60)
                continue
            elif e.code == 429:
                retry_after = e.headers.get("Retry-After")
                wait = int(retry_after) if retry_after else 120
                print(f"  Secondary rate limit (429). Waiting {wait}s...")
                time.sleep(wait)
                continue
            elif e.code >= 500:
                wait = (2 ** attempt) * 5
                print(f"  Server error ({e.code}). Retry in {wait}s...")
                time.sleep(wait)
                continue
            else:
                print(f"  HTTP {e.code} for {date_str}: {e.reason}", file=sys.stderr)
                return None
        except (urllib.error.URLError, OSError) as e:
            wait = (2 ** attempt) * 5
            print(f"  Network error: {e}. Retry in {wait}s...")
            time.sleep(wait)
            continue

    return None  # all retries exhausted


def date_range(start_str, end_date):
    current = datetime.strptime(start_str, "%Y-%m-%d").date()
    while current <= end_date:
        yield current.isoformat()
        current += timedelta(days=1)


def main():
    token = get_token()
    data = load_data()
    contributions = data["contributions"]
    failed_dates = set(data.get("failed_dates", []))

    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()

    # Build list of dates to fetch
    dates_to_fetch = []

    # First: retry previously failed dates
    for d in sorted(failed_dates):
        dates_to_fetch.append(d)

    # Then: all missing dates from start to yesterday
    for d in date_range(START_DATE, yesterday):
        if d not in contributions and d not in failed_dates:
            dates_to_fetch.append(d)

    if not dates_to_fetch:
        print("All dates already collected. Nothing to do.")
        return

    print(f"Dates to fetch: {len(dates_to_fetch)}")
    print(f"Already collected: {len(contributions)}")
    print(f"Previously failed: {len(failed_dates)}")
    print()

    request_count = 0
    new_successes = 0
    new_failures = 0

    for i, date_str in enumerate(dates_to_fetch):
        # Cooldown
        if request_count > 0 and request_count % COOLDOWN_EVERY == 0:
            print(f"\n--- Cooldown: {COOLDOWN_SECONDS}s after {request_count} requests ---\n")
            time.sleep(COOLDOWN_SECONDS)

        count = fetch_commit_count(date_str, token)
        request_count += 1

        if count is not None:
            contributions[date_str] = count
            failed_dates.discard(date_str)
            new_successes += 1
            print(f"[{i+1}/{len(dates_to_fetch)}] {date_str}: {count:,} commits")
        else:
            failed_dates.add(date_str)
            new_failures += 1
            print(f"[{i+1}/{len(dates_to_fetch)}] {date_str}: FAILED")

        # Checkpoint
        if new_successes > 0 and new_successes % CHECKPOINT_EVERY == 0:
            data["failed_dates"] = sorted(failed_dates)
            save_data(data)
            print(f"  [Checkpoint saved: {len(contributions)} dates]")

        time.sleep(REQUEST_INTERVAL)

    # Final save
    data["failed_dates"] = sorted(failed_dates)
    save_data(data)

    print(f"\nDone!")
    print(f"  Successful: {new_successes}")
    print(f"  Failed: {new_failures}")
    print(f"  Total dates: {len(contributions)}")
    print(f"  Total commits: {sum(contributions.values()):,}")
    if failed_dates:
        print(f"  Failed dates remaining: {len(failed_dates)}")


if __name__ == "__main__":
    main()
