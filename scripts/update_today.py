#!/usr/bin/env python3
"""
update_today.py - 정기 업데이트 스크립트.

--today-only: 오늘만 업데이트 (15분마다 실행용)
플래그 없음: 오늘 + 어제 + failed 재시도 (1시간마다 실행용)
"""

import argparse
import time
from datetime import datetime, timedelta, timezone

from github_api import (
    fetch_unique_repo_count,
    get_token,
    load_data,
    save_data,
)

REQUEST_INTERVAL = 2.2
MAX_FAILED_RETRY = 5


def main():
    parser = argparse.ArgumentParser(description="Update Claude Index data")
    parser.add_argument("--today-only", action="store_true",
                        help="Only update today's data (for 15-min cron)")
    args = parser.parse_args()

    token = get_token()
    data = load_data()
    contributions = data["contributions"]
    failed_dates = set(data.get("failed_dates", []))

    now_utc = datetime.now(timezone.utc)
    today = now_utc.date().isoformat()
    yesterday = (now_utc - timedelta(days=1)).date().isoformat()

    if args.today_only:
        dates_to_fetch = [today]
    else:
        dates_to_fetch = [yesterday, today]
        # Add failed dates (up to MAX_FAILED_RETRY)
        retry_dates = sorted(failed_dates)[:MAX_FAILED_RETRY]
        for d in retry_dates:
            if d not in dates_to_fetch:
                dates_to_fetch.append(d)

    changed = False

    for date_str in dates_to_fetch:
        count = fetch_unique_repo_count(date_str, token, REQUEST_INTERVAL)

        if count is not None:
            old_val = contributions.get(date_str)
            contributions[date_str] = count
            failed_dates.discard(date_str)
            if old_val != count:
                changed = True
            print(f"{date_str}: {count:,} unique repos")
        else:
            failed_dates.add(date_str)
            print(f"{date_str}: FAILED")
            changed = True

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
