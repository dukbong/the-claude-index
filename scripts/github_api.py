"""
github_api.py - GitHub Search API 공통 모듈.

initial_scrape.py와 update_today.py에서 공유하는 함수와 상수를 제공한다.
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
MAX_RETRIES = 3
DATA_VERSION = 2


def get_token():
    """GitHub 토큰을 환경변수 또는 gh CLI에서 획득한다."""
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
    """contributions.json을 읽어 반환한다. 파일이 없으면 초기 구조를 반환.

    v1 포맷(total_commits) 감지 시 v2(total_repos)로 마이그레이션하고
    contributions를 초기화한다.
    """
    if DATA_FILE.exists():
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
        if data.get("metadata", {}).get("data_version") != DATA_VERSION:
            data["metadata"]["data_version"] = DATA_VERSION
            data["metadata"].pop("total_commits", None)
            data["metadata"]["total_repos"] = 0
            data["contributions"] = {}
            data["failed_dates"] = []
        return data
    return {
        "last_updated": None,
        "metadata": {
            "username": USERNAME,
            "user_id": USER_ID,
            "scrape_start_date": START_DATE,
            "total_repos": 0,
            "data_version": DATA_VERSION,
        },
        "contributions": {},
        "failed_dates": [],
    }


def save_data(data):
    """contributions.json을 원자적으로 저장한다."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data["metadata"]["total_repos"] = sum(data["contributions"].values())
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


def _api_request(url, token):
    """GitHub API에 HTTP 요청을 보내고 JSON을 반환한다. 재시도/rate limit 처리 포함."""
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("User-Agent", "the-claude-index-scraper")

    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
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
                print(f"  HTTP {e.code} for {url}: {e.reason}", file=sys.stderr)
                return None
        except (urllib.error.URLError, OSError) as e:
            wait = (2 ** attempt) * 5
            print(f"  Network error: {e}. Retry in {wait}s...")
            time.sleep(wait)
            continue

    return None  # all retries exhausted


def fetch_commit_count(date_str, token, request_interval=2.2):
    """주어진 날짜의 @claude 커밋 수를 반환한다. 실패 시 None."""
    url = (
        f"https://api.github.com/search/commits"
        f"?q=author:{USERNAME}+author-date:{date_str}"
        f"&per_page=1"
    )
    body = _api_request(url, token)
    if body is None:
        return None
    return body.get("total_count", 0)


# --- Unique repo count functions ---


def _time_to_minutes(time_str):
    """'HH:MM' 형식을 분 단위 정수로 변환."""
    h, m = time_str.split(":")
    return int(h) * 60 + int(m)


def _minutes_to_time(minutes):
    """분 단위 정수를 'HH:MM' 형식으로 변환."""
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _fetch_commits_page(query, token, page, per_page=100):
    """커밋 검색 결과 1페이지를 반환한다."""
    q = query.replace(" ", "+")
    url = (
        f"https://api.github.com/search/commits"
        f"?q={q}&per_page={per_page}&page={page}"
    )
    return _api_request(url, token)


def _build_time_query(date_str, start_time, end_time):
    """시간 범위 쿼리 문자열을 생성한다. GitHub range(..) 문법 사용."""
    start_part = f"{date_str}T{start_time}:00"
    if end_time == "24:00":
        next_day = (
            datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)
        ).strftime("%Y-%m-%d")
        end_part = f"{next_day}T00:00:00"
    else:
        end_part = f"{date_str}T{end_time}:00"
    return f"author:{USERNAME} author-date:{start_part}..{end_part}"


def _fetch_repos_for_window(date_str, time_range, token, request_interval):
    """특정 시간 창의 고유 레포 set을 반환한다.

    Args:
        time_range: None이면 하루 전체, (start, end) 튜플이면 해당 시간 창.

    Returns:
        (repos_set, total_count) 또는 total_count > 1000이면 (None, total_count).
        API 실패 시 None.
    """
    if time_range is None:
        query = f"author:{USERNAME} author-date:{date_str}"
    else:
        query = _build_time_query(date_str, time_range[0], time_range[1])

    body = _fetch_commits_page(query, token, page=1, per_page=1)
    if body is None:
        return None

    total_count = body.get("total_count", 0)
    if total_count == 0:
        return (set(), 0)
    if total_count > 1000:
        return (None, total_count)

    # Paginate to collect unique repos
    repos = set()
    pages_needed = (total_count + 99) // 100
    for page in range(1, pages_needed + 1):
        time.sleep(request_interval)
        body = _fetch_commits_page(query, token, page=page, per_page=100)
        if body is None:
            continue
        for item in body.get("items", []):
            repo = item.get("repository", {})
            full_name = repo.get("full_name")
            if full_name:
                repos.add(full_name)

    return (repos, total_count)


def _fetch_repos_adaptive(date_str, start_time, end_time, token, request_interval,
                          depth=0, max_depth=5):
    """재귀적 시간 분할로 고유 레포를 수집한다.

    1000건 초과 시 시간 창을 동적으로 분할하여 재귀 호출.
    """
    result = _fetch_repos_for_window(
        date_str, (start_time, end_time), token, request_interval
    )
    if result is None:
        return None

    repos, total_count = result
    if repos is not None:
        return repos

    # Need to split — check if we can
    start_min = _time_to_minutes(start_time)
    end_min = _time_to_minutes(end_time)
    span = end_min - start_min

    if depth >= max_depth or span < 2:
        # Can't split further, fetch first 1000 results as best effort
        print(f"  Warning: {'max depth' if depth >= max_depth else 'min span'} reached for "
              f"{date_str} {start_time}-{end_time} ({total_count:,} commits)")
        repos = set()
        query = _build_time_query(date_str, start_time, end_time)
        for page in range(1, 11):
            time.sleep(request_interval)
            body = _fetch_commits_page(query, token, page=page, per_page=100)
            if body is None:
                break
            items = body.get("items", [])
            if not items:
                break
            for item in items:
                repo = item.get("repository", {})
                full_name = repo.get("full_name")
                if full_name:
                    repos.add(full_name)
        return repos

    n_splits = min(max(2, total_count // 800), 12)
    n_splits = min(n_splits, span)

    all_repos = set()
    step = span / n_splits

    for i in range(n_splits):
        sub_start = start_min + int(i * step)
        sub_end = start_min + int((i + 1) * step)
        if i == n_splits - 1:
            sub_end = end_min

        sub_start_str = _minutes_to_time(sub_start)
        sub_end_str = _minutes_to_time(sub_end)

        print(f"  {'  ' * depth}Split: {date_str} "
              f"{sub_start_str}-{sub_end_str} (depth={depth + 1})")

        time.sleep(request_interval)
        sub_repos = _fetch_repos_adaptive(
            date_str, sub_start_str, sub_end_str,
            token, request_interval, depth + 1, max_depth
        )
        if sub_repos is not None:
            all_repos.update(sub_repos)

    return all_repos


def fetch_unique_repo_count(date_str, token, request_interval=2.2):
    """주어진 날짜의 @claude 고유 레포 수를 반환한다. 실패 시 None."""
    result = _fetch_repos_for_window(date_str, None, token, request_interval)
    if result is None:
        return None

    repos, total_count = result
    if repos is not None:
        return len(repos)

    # > 1000 commits, use adaptive time splitting
    print(f"  {date_str}: {total_count:,} commits, using adaptive time splitting...")
    time.sleep(request_interval)
    repos = _fetch_repos_adaptive(
        date_str, "00:00", "24:00", token, request_interval
    )
    if repos is None:
        return None
    return len(repos)
