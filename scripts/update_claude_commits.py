#!/usr/bin/env python3
"""
update_claude_commits.py - 오늘/어제 Claude 커밋 수를 업데이트하고 실패 날짜를 재시도한다.

API 호출: 오늘 1 + 어제 1 + failed_dates 최대 5 = 최대 7회/실행.
"""

import time
from datetime import datetime, timedelta, timezone

from github_api import (
    fetch_claude_commits,
    get_token,
    load_commits_data,
    save_commits_data,
)

REQUEST_INTERVAL = 2.2
MAX_FAILED_RETRIES = 5


def main():
    token = get_token()
    data = load_commits_data()

    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")

    updated = False

    for date_str in [today, yesterday]:
        print(f"Fetching {date_str}...")
        count = fetch_claude_commits(date_str, token)
        if count is not None:
            data["daily"][date_str] = count
            print(f"  {date_str}: {count:,} commits")
            updated = True
        else:
            print(f"  {date_str}: FAILED")
            if date_str not in data.get("failed_dates", []):
                data.setdefault("failed_dates", []).append(date_str)
        time.sleep(REQUEST_INTERVAL)

    # Retry failed dates (newest first, max 5)
    failed = sorted(data.get("failed_dates", []), reverse=True)
    retried = []
    for date_str in failed[:MAX_FAILED_RETRIES]:
        if date_str in [today, yesterday]:
            continue
        print(f"Retrying {date_str}...")
        count = fetch_claude_commits(date_str, token)
        if count is not None:
            data["daily"][date_str] = count
            retried.append(date_str)
            print(f"  {date_str}: {count:,} commits (recovered)")
            updated = True
        else:
            print(f"  {date_str}: still failing")
        time.sleep(REQUEST_INTERVAL)

    data["failed_dates"] = [d for d in data.get("failed_dates", []) if d not in retried]
    # Remove today/yesterday from failed if they succeeded
    data["failed_dates"] = [
        d for d in data["failed_dates"]
        if not (d in [today, yesterday] and d in data["daily"])
    ]

    if updated:
        save_commits_data(data)
        total = data["metadata"]["total_commits"]
        print(f"Saved. Total: {total:,} commits across {len(data['daily'])} days.")
    else:
        print("No updates.")


if __name__ == "__main__":
    main()
