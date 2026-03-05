"""
github_api.py - GitHub Search API 공통 모듈.

Claude 커밋 추적에 사용하는 함수와 상수를 제공한다.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR.parent / "data"
COMMITS_DATA_FILE = DATA_DIR / "claude_commits.json"

SEARCH_QUERY = '"noreply@anthropic.com"'
START_DATE = "2025-01-01"
MAX_RETRIES = 3


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

    return None


def fetch_claude_commits(date_str, token):
    """주어진 날짜의 Claude 커밋 수를 반환. 실패 시 None.

    커밋 메시지/메타데이터에서 noreply@anthropic.com 문자열을 full-text 검색.
    Co-Authored-By trailer에 포함된 Anthropic 이메일을 매칭한다.
    """
    url = (
        f"https://api.github.com/search/commits"
        f'?q="noreply@anthropic.com"+author-date:{date_str}'
        f"&per_page=1"
    )
    body = _api_request(url, token)
    return body.get("total_count", 0) if body else None


def load_commits_data():
    """claude_commits.json을 읽어 반환한다. 파일이 없으면 초기 구조를 반환."""
    if COMMITS_DATA_FILE.exists():
        with open(COMMITS_DATA_FILE, "r") as f:
            return json.load(f)
    return {
        "last_updated": None,
        "metadata": {
            "data_version": 1,
            "description": "Daily Claude-authored commit counts on GitHub",
            "query": "noreply@anthropic.com",
            "total_commits": 0,
        },
        "daily": {},
        "failed_dates": [],
    }


def save_commits_data(data):
    """claude_commits.json을 원자적으로 저장한다."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data["metadata"]["total_commits"] = sum(data["daily"].values())
    tmp_fd, tmp_path = tempfile.mkstemp(dir=DATA_DIR, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp_path, COMMITS_DATA_FILE)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
