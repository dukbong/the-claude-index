#!/usr/bin/env python3
"""
update_doc_markers.py

GitHub 저장소에서 AI 에이전트 문서 도입 신호를 수집한다.
기본 지표는 각 문서명별 "일일 신규 레포 수(전역 중복 제거, 비누적)".

Method (v1):
- 후보 레포: GitHub repository search (`<FILE> in:path`)
- 파일 확인: root 경로(`/contents/<FILE>`) 존재 검사
- 최초 도입일: `/commits?path=<FILE>`의 가장 오래된 커밋 날짜

주의:
- root 파일 기준만 집계한다.
- search API 특성상 후보 누락 가능성이 있어 절대치보다 추세 해석에 적합하다.
"""

import json
import re
import sys
import time
import argparse
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from github_api import get_token

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR.parent / "data"
OUT_FILE = DATA_DIR / "ai_docs_index.json"

DATA_VERSION = 1
REQUEST_INTERVAL = 0.35
CHECKPOINT_EVERY = 25
MAX_RETRIES = 4

MARKERS = {
    "claude": "CLAUDE.md",
    "gemini": "GEMINI.md",
    "agents": "AGENTS.md",
}


def _now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _empty_state():
    return {
        "last_updated": None,
        "metadata": {
            "data_version": DATA_VERSION,
            "method": "repo_search + root_contents + commit_path_first_seen",
            "markers": MARKERS,
            "root_only": True,
        },
        "series": {},
        "totals": {},
        "repo_first_seen": {k: {} for k in MARKERS},
        "failed_repos": {k: [] for k in MARKERS},
        "progress": {},
    }


def load_state():
    if not OUT_FILE.exists():
        return _empty_state()

    with open(OUT_FILE, "r") as f:
        data = json.load(f)

    if data.get("metadata", {}).get("data_version") != DATA_VERSION:
        return _empty_state()

    data.setdefault("series", {})
    data.setdefault("totals", {})
    data.setdefault("repo_first_seen", {})
    data.setdefault("failed_repos", {})
    data.setdefault("progress", {})
    for key in MARKERS:
        data["repo_first_seen"].setdefault(key, {})
        data["failed_repos"].setdefault(key, [])

    return data


def save_state(data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data["last_updated"] = _now_utc()
    tmp = OUT_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    tmp.replace(OUT_FILE)


def _build_req(url, token):
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "the-claude-index-doc-markers")
    return req


def _wait_rate_limit(headers):
    reset = headers.get("X-RateLimit-Reset")
    if reset:
        wait = max(int(reset) - int(time.time()) + 1, 1)
    else:
        wait = 60
    print(f"  Rate limited. Waiting {wait}s...")
    time.sleep(wait)


def api_get_json(url, token):
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(_build_req(url, token), timeout=40) as resp:
                body = json.loads(resp.read().decode())
                headers = {k: v for k, v in resp.headers.items()}
                return body, headers, resp.status
        except urllib.error.HTTPError as e:
            headers = {k: v for k, v in e.headers.items()} if e.headers else {}
            if e.code == 404:
                return None, headers, 404
            if e.code in (403, 429):
                _wait_rate_limit(headers)
                continue
            if e.code >= 500:
                wait = (2 ** attempt) * 3
                print(f"  Server error {e.code}. Retry in {wait}s...")
                time.sleep(wait)
                continue
            msg = e.read().decode(errors="ignore")
            print(f"  HTTP {e.code} for {url}: {msg[:200]}", file=sys.stderr)
            return None, headers, e.code
        except (urllib.error.URLError, OSError) as e:
            wait = (2 ** attempt) * 3
            print(f"  Network error: {e}. Retry in {wait}s...")
            time.sleep(wait)
            continue
    return None, {}, None


def search_candidate_repos_repo(filename, token):
    q = urllib.parse.quote_plus(f"{filename} in:path")
    page = 1
    repos = []
    total = 0

    while True:
        url = f"https://api.github.com/search/repositories?q={q}&per_page=100&page={page}"
        body, _, status = api_get_json(url, token)
        if status != 200 or body is None:
            break
        if page == 1:
            total = body.get("total_count", 0)
        items = body.get("items", [])
        if not items:
            break
        repos.extend(item["full_name"] for item in items if "full_name" in item)

        # Search API는 최대 1000개 결과만 페이지네이션 가능
        if page >= 10:
            break
        page += 1
        time.sleep(REQUEST_INTERVAL)

    return sorted(set(repos)), total


def search_candidate_repos_code(filename, token, pages=1):
    q = urllib.parse.quote_plus(f"filename:{filename} path:/")
    repo_paths = {}
    total = 0
    max_pages = max(1, min(pages, 10))

    for page in range(1, max_pages + 1):
        url = f"https://api.github.com/search/code?q={q}&per_page=100&page={page}"
        body, _, status = api_get_json(url, token)
        if status != 200 or body is None:
            break
        if page == 1:
            total = body.get("total_count", 0)
        items = body.get("items", [])
        if not items:
            break
        for item in items:
            repo = item.get("repository", {})
            full_name = repo.get("full_name")
            path = item.get("path")
            if full_name and path:
                if full_name not in repo_paths:
                    repo_paths[full_name] = set()
                repo_paths[full_name].add(path)
        time.sleep(REQUEST_INTERVAL)

    return repo_paths, total


def root_file_exists(repo_full_name, filename, token):
    safe_repo = urllib.parse.quote(repo_full_name, safe="/")
    safe_path = urllib.parse.quote(filename, safe="")
    url = f"https://api.github.com/repos/{safe_repo}/contents/{safe_path}"
    _, _, status = api_get_json(url, token)
    return status == 200


def _extract_last_page(link_header):
    if not link_header:
        return 1
    m = re.search(r"[?&]page=(\d+)>;\s*rel=\"last\"", link_header)
    if not m:
        return 1
    return int(m.group(1))


def first_commit_date_for_path(repo_full_name, file_path, token):
    safe_repo = urllib.parse.quote(repo_full_name, safe="/")
    safe_path = urllib.parse.quote(file_path, safe="")
    base = (
        f"https://api.github.com/repos/{safe_repo}/commits"
        f"?path={safe_path}&per_page=1"
    )

    first_page_body, headers, status = api_get_json(base + "&page=1", token)
    if status != 200 or first_page_body is None:
        return None
    if not first_page_body:
        return None

    last_page = _extract_last_page(headers.get("Link", ""))
    if last_page == 1:
        item = first_page_body[0]
    else:
        time.sleep(REQUEST_INTERVAL)
        last_page_body, _, status = api_get_json(base + f"&page={last_page}", token)
        if status != 200 or not last_page_body:
            return None
        item = last_page_body[0]

    commit = item.get("commit", {})
    author = commit.get("author", {}) or {}
    committer = commit.get("committer", {}) or {}
    date_str = author.get("date") or committer.get("date")
    if not date_str:
        return None
    return date_str[:10]


def build_daily_counts(repo_first_seen):
    counts = {}
    for first_seen in repo_first_seen.values():
        counts[first_seen] = counts.get(first_seen, 0) + 1
    return dict(sorted(counts.items()))


def process_marker(
    state,
    marker_key,
    filename,
    token,
    max_candidates=None,
    candidate_mode="repo",
    code_pages=1,
    ignore_failed=False,
):
    repo_first_seen = state["repo_first_seen"][marker_key]
    failed = set()
    if not ignore_failed:
        failed = set(state["failed_repos"][marker_key])

    candidate_paths_by_repo = {}
    if candidate_mode == "code":
        candidate_paths_by_repo, total_candidates = search_candidate_repos_code(
            filename, token, pages=code_pages
        )
        candidates = sorted(candidate_paths_by_repo.keys())
    else:
        candidates, total_candidates = search_candidate_repos_repo(filename, token)
    if max_candidates is not None:
        candidates = candidates[:max_candidates]
    print(
        f"\n[{marker_key}] candidate repos: {len(candidates)} "
        f"(search total_count={total_candidates:,})"
    )

    processed = 0
    scanned = 0
    new_found = 0
    start_ts = time.time()

    for i, repo in enumerate(candidates, start=1):
        if repo in repo_first_seen or repo in failed:
            continue

        scanned += 1
        if candidate_mode == "repo":
            time.sleep(REQUEST_INTERVAL)
            if not root_file_exists(repo, filename, token):
                failed.add(repo)
                continue

        first_seen = None
        if candidate_mode == "code":
            paths = sorted(candidate_paths_by_repo.get(repo, []))
            for path in paths:
                time.sleep(REQUEST_INTERVAL)
                path_first_seen = first_commit_date_for_path(repo, path, token)
                if path_first_seen is None:
                    continue
                if first_seen is None or path_first_seen < first_seen:
                    first_seen = path_first_seen
        else:
            time.sleep(REQUEST_INTERVAL)
            first_seen = first_commit_date_for_path(repo, filename, token)
        if first_seen is None:
            failed.add(repo)
            continue

        repo_first_seen[repo] = first_seen
        new_found += 1
        processed += 1

        print(f"  [{marker_key} {i}/{len(candidates)}] {repo} -> {first_seen}")

        if processed > 0 and processed % CHECKPOINT_EVERY == 0:
            state["failed_repos"][marker_key] = sorted(failed)
            state["series"][marker_key] = build_daily_counts(repo_first_seen)
            state["totals"][marker_key] = len(repo_first_seen)
            state["progress"][marker_key] = {
                "last_run": _now_utc(),
                "candidate_count": len(candidates),
                "search_total_count": total_candidates,
                "processed_new": processed,
                "scanned_this_run": scanned,
                "elapsed_sec": round(time.time() - start_ts, 1),
            }
            save_state(state)
            print(f"  [checkpoint] {marker_key}: total unique repos={len(repo_first_seen):,}")

    state["failed_repos"][marker_key] = sorted(failed)
    state["series"][marker_key] = build_daily_counts(repo_first_seen)
    state["totals"][marker_key] = len(repo_first_seen)
    state["progress"][marker_key] = {
        "last_run": _now_utc(),
        "candidate_count": len(candidates),
        "search_total_count": total_candidates,
        "processed_new": processed,
        "new_found": new_found,
        "scanned_this_run": scanned,
        "elapsed_sec": round(time.time() - start_ts, 1),
    }

    print(
        f"[{marker_key}] done: unique repos={len(repo_first_seen):,}, "
        f"new_found={new_found}, failed={len(failed)}"
    )


def main():
    parser = argparse.ArgumentParser(description="Update marker-based daily new repo index")
    parser.add_argument(
        "--max-candidates",
        type=int,
        default=None,
        help="Only process first N candidate repos per marker (for quick sampling)",
    )
    parser.add_argument(
        "--markers",
        default="claude,gemini,agents",
        help="Comma-separated marker keys to process (claude,gemini,agents)",
    )
    parser.add_argument(
        "--candidate-mode",
        choices=["repo", "code"],
        default="repo",
        help="Candidate discovery mode: repo search (broad) or code search (accurate, stricter rate limit)",
    )
    parser.add_argument(
        "--code-pages",
        type=int,
        default=1,
        help="When --candidate-mode=code, pages to fetch per marker (1-10)",
    )
    parser.add_argument(
        "--ignore-failed",
        action="store_true",
        help="Do not skip repos recorded in failed_repos from previous runs",
    )
    args = parser.parse_args()

    selected_markers = []
    for key in [k.strip().lower() for k in args.markers.split(",") if k.strip()]:
        if key in MARKERS and key not in selected_markers:
            selected_markers.append(key)
    if not selected_markers:
        raise SystemExit("No valid markers selected. Use --markers with claude,gemini,agents.")

    token = get_token()
    state = load_state()
    metadata = state.setdefault("metadata", {})
    metadata["data_version"] = DATA_VERSION
    metadata["markers"] = MARKERS
    if args.candidate_mode == "code":
        metadata["method"] = "code_search(path)+commit_path_first_seen"
        metadata["root_only"] = False
    else:
        metadata["method"] = "repo_search + root_contents + commit_path_first_seen"
        metadata["root_only"] = True
    save_state(state)

    try:
        for marker_key in selected_markers:
            filename = MARKERS[marker_key]
            process_marker(
                state,
                marker_key,
                filename,
                token,
                max_candidates=args.max_candidates,
                candidate_mode=args.candidate_mode,
                code_pages=args.code_pages,
                ignore_failed=args.ignore_failed,
            )
            save_state(state)
    except KeyboardInterrupt:
        save_state(state)
        print("\nInterrupted. Progress checkpoint saved.")
        raise

    print("\nDone.")
    for k in selected_markers:
        print(f"  {k}: {state['totals'].get(k, 0):,} unique repos")


if __name__ == "__main__":
    main()
