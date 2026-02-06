#!/usr/bin/env python3
"""
initial_scrape.py - GitHub Search API로 @claude 계정의 일별 커밋 수를 수집.

시작일(2024-01-01)부터 어제까지 모든 날짜에 대해 커밋 수를 가져온다.
체크포인트 저장, 중단 후 재개, failed_dates 재시도를 지원한다.
"""

import time
from datetime import datetime, timedelta, timezone

from github_api import (
    START_DATE,
    fetch_commit_count,
    get_token,
    load_data,
    save_data,
)

REQUEST_INTERVAL = 2.2  # seconds between requests
CHECKPOINT_EVERY = 25
COOLDOWN_EVERY = 150
COOLDOWN_SECONDS = 60


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

        count = fetch_commit_count(date_str, token, REQUEST_INTERVAL)
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
