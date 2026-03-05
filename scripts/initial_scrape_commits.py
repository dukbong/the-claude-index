#!/usr/bin/env python3
"""
initial_scrape_commits.py - 과거 데이터 백필용 스크립트.

START_DATE부터 어제까지 빈 날짜를 채운다.
25개마다 체크포인트 저장.
"""

import time
from datetime import datetime, timedelta, timezone

from github_api import (
    START_DATE,
    fetch_claude_commits,
    get_token,
    load_commits_data,
    save_commits_data,
)

REQUEST_INTERVAL = 2.5
CHECKPOINT_INTERVAL = 25


def main():
    token = get_token()
    data = load_commits_data()

    start = datetime.strptime(START_DATE, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    yesterday = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)

    # Build list of dates to fetch
    dates_to_fetch = []
    current = start
    while current <= yesterday:
        date_str = current.strftime("%Y-%m-%d")
        if date_str not in data["daily"]:
            dates_to_fetch.append(date_str)
        current += timedelta(days=1)

    if not dates_to_fetch:
        print("All dates already filled.")
        return

    print(f"Fetching {len(dates_to_fetch)} dates ({dates_to_fetch[0]} to {dates_to_fetch[-1]})...")

    fetched = 0
    failed = []
    for i, date_str in enumerate(dates_to_fetch):
        print(f"[{i + 1}/{len(dates_to_fetch)}] {date_str}...", end=" ")
        count = fetch_claude_commits(date_str, token)
        if count is not None:
            data["daily"][date_str] = count
            print(f"{count:,}")
            fetched += 1
        else:
            print("FAILED")
            failed.append(date_str)

        # Checkpoint
        if (i + 1) % CHECKPOINT_INTERVAL == 0:
            data["failed_dates"] = list(set(data.get("failed_dates", []) + failed))
            save_commits_data(data)
            print(f"  -- Checkpoint saved ({fetched} fetched, {len(failed)} failed) --")

        time.sleep(REQUEST_INTERVAL)

    # Final save
    data["failed_dates"] = list(set(data.get("failed_dates", []) + failed))
    # Remove from failed_dates if they were actually fetched
    data["failed_dates"] = [d for d in data["failed_dates"] if d not in data["daily"]]
    save_commits_data(data)

    total = data["metadata"]["total_commits"]
    print(f"\nDone. Fetched {fetched}, failed {len(failed)}.")
    print(f"Total: {total:,} commits across {len(data['daily'])} days.")


if __name__ == "__main__":
    main()
