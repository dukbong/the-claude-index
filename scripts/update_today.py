#!/usr/bin/env python3
"""
update_today.py - 매시간 실행되는 경량 업데이트 스크립트.

오늘 + 어제 2일치 데이터를 가져오고, failed_dates도 최대 10건 재시도한다.
변경이 없으면 파일을 수정하지 않는다.
"""

import time
from datetime import datetime, timedelta, timezone

from github_api import (
    fetch_commit_count,
    get_token,
    load_data,
    save_data,
)

REQUEST_INTERVAL = 2.2
MAX_FAILED_RETRY = 10


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
        count = fetch_commit_count(date_str, token, REQUEST_INTERVAL)

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
