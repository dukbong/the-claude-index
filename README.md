# The Claude Index

> One chart with three lines: daily new repos adopting `CLAUDE.md`, `GEMINI.md`, `AGENTS.md` (ChatGPT/Agents).

![The Claude Index Dashboard](docs/screenshot.png)

## About

The Claude Index is a live dashboard that tracks AI-agent documentation adoption across public repositories.

Each line shows **Daily New Repos** for one marker file:
- `CLAUDE.md`
- `GEMINI.md`
- `AGENTS.md` (ChatGPT/Agents ecosystem)

Counts are globally deduplicated by repository and are non-cumulative.

## Live Dashboard

**[https://dukbong.github.io/the-claude-index/](https://dukbong.github.io/the-claude-index/)**

## Metrics

| Metric | Description |
|--------|-------------|
| **Claude (Today/Yesterday)** | Daily new repos for `CLAUDE.md` |
| **Gemini (Today/Yesterday)** | Daily new repos for `GEMINI.md` |
| **ChatGPT/Agents (Today/Yesterday)** | Daily new repos for `AGENTS.md` |
| **Total Unique Repos** | Total deduplicated repositories across all three lines |

## How It Works

1. **GitHub Search API** finds repository candidates for each marker file
2. Candidate repositories are validated against root-path marker files
3. Earliest commit date for that file path is used as repository first-seen date
4. Daily counts are built from first-seen dates (global dedupe, non-cumulative)
4. Data is stored in:
   - `data/ai_docs_index.json` (daily series + repo first-seen map)
5. Interactive chart is rendered with **Chart.js** (zoom/pan support)

## Operational Notes

- Run `python scripts/update_doc_markers.py --candidate-mode code --code-pages 1` to refresh marker adoption data.
- For a quick local sample, use `python scripts/update_doc_markers.py --candidate-mode code --code-pages 1 --max-candidates 20 --ignore-failed`.
- GitHub search APIs are rate-limited; large refreshes may require multiple runs.

## Tech Stack

- **Frontend:** HTML, CSS, JavaScript, Chart.js
- **Data Collection:** Python 3.12, GitHub Search API
- **Automation:** GitHub Actions
- **Hosting:** GitHub Pages
