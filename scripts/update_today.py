#!/usr/bin/env python3
"""
update_today.py - 매시간 실행되는 경량 업데이트 스크립트.

오늘 + 어제 2일치 데이터를 가져오고, failed_dates도 최대 10건 재시도한다.
변경이 없으면 파일을 수정하지 않는다.
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
REQUEST_INTERVAL = 2.2
MAX_RETRIES = 3
MAX_FAILED_RETRY = 10


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
            "scrape_start_date": "2024-01-01",
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

    return None


def main():
    token = get_token()
    data = load_data()
    contributions = data["contributions"]
    failed_dates = set(data.get("failed_dates", []))

    now_utc = datetime.now(timezone.utc)
    today = now_utc.date().isoformat()
    yesterday = (now_utc - timedelta(days=1)).date().isoformat()

    dates_to_fetch = [yesterday, today]

    # Add failed dates (up to MAX_FAILED_RETRY)
    retry_dates = sorted(failed_dates)[:MAX_FAILED_RETRY]
    for d in retry_dates:
        if d not in dates_to_fetch:
            dates_to_fetch.append(d)

    original_snapshot = {d: contributions.get(d) for d in dates_to_fetch}
    changed = False

    for date_str in dates_to_fetch:
        count = fetch_commit_count(date_str, token)

        if count is not None:
            old_val = contributions.get(date_str)
            contributions[date_str] = count
            failed_dates.discard(date_str)
            if old_val != count:
                changed = True
            print(f"{date_str}: {count:,} commits")
        else:
            failed_dates.add(date_str)
            print(f"{date_str}: FAILED")
            changed = True  # failed_dates changed

        time.sleep(REQUEST_INTERVAL)

    old_failed = set(data.get("failed_dates", []))
    if failed_dates != old_failed:
        changed = True

    if changed:
        data["failed_dates"] = sorted(failed_dates)
        save_data(data)
        print("Data updated.")
    else:
        print("No changes detected. File not modified.")


if __name__ == "__main__":
    main()
