# NFM — News Feed Manager

NFM is a self-hosted, personalized RSS news reader built around semantic deduplication, user-specific filtering, and click-driven ML tagging. The app aggregates feeds from multiple sources, filters and ranks articles for a user, and can serve a web UI or scheduled email digest without requiring a database.

Built with FastAPI, designed to run comfortably on low-resource hardware (Raspberry Pi compatible).
Well suited for mobile clients:

<p align="center">
<img src="doc/images/sh01.png" width="400" alt="Screenshot01">
<img src="doc/images/sh02.png" width="400" alt="Screenshot01">
</p>
<p style="text-align: center;">
To avoid copyright disputes, the article summary has been blurred...
</p>


## Features

- **Multi-source RSS aggregation** — fetches feeds asynchronously (bounded concurrency) from any number of configured sources
- **Semantic deduplication** — two-stage pipeline (TF-IDF pre-filter + sentence-transformer similarity) collapses near-identical stories reported by multiple outlets
- **Per-user personalization** — each user has their own feed list, blacklist/highlight keywords, and delivery channels (web and/or email)
- **ML-based interest tagging 💡** — a lightweight classifier learns from your click behavior ("liked" vs. "marked as read") and highlights new stories similar to what you've engaged with before, retraining automatically as click data accumulates
- **Paywall detection** — flags articles likely to be behind a paywall based on heuristic content scoring
- **Web UI + Email digest** — browse via a responsive web page, well suited for mobile clients or receive a scheduled HTML email digest
- **No database** — all state lives in JSON/JSONL files on disk

## Stack

- FastAPI
- Jinja2
- APScheduler
- feedparser
- scikit-learn
- sentence-transformers
- PyTorch (CPU build)
- uv for environment management

## Architecture

```
RSS feeds → async fetch → semantic dedup → personalized filtering → render (web/email) → click tracking → ML retraining
```

| Component | Responsibility |
|---|---|
| `main.py` | FastAPI app, APScheduler jobs (hourly feed refresh, daily email) |
| `main_web_eval.py` | Lightweight dev server that serves precomputed render data for fast UI iteration |
| `app/core/feedmgr.py` | `NewsFeedManager` — coordinates all configured users |
| `app/core/feedprocessor.py` | Async RSS fetching with concurrency limits |
| `app/core/dedup.py` | TF-IDF + sentence-transformer semantic deduplication |
| `app/core/ml.py` | Per-user click-based interest tagging and model retraining |
| `app/core/filter.py` | Source-specific description cleaners |
| `app/core/tools.py` | Filters (blacklist, paywall, time window), email sending, link-ID hashing |
| `app/core/render.py` | Jinja2 rendering with embedded assets for email compatibility |
| `app/conf/config.py` | Users, feeds, blacklists, highlight keywords, ML settings |

## Getting Started

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) for dependency and virtual environment management

### Installation

```bash
git clone <this-repo>
cd nfm
uv sync
```

### Configuration

1. Copy the secrets template and fill in your SMTP credentials (only needed for email delivery):
2. Edit `app/conf/config.py` to define your own user(s), feed lists, blacklist/highlight keywords, and scheduling. See `config_user01` for a complete example.

### Running Locally

```bash
# Full pipeline: live RSS fetching, scheduler, ML tagging
uv run --active main.py --reload
```

Once running, open `http://localhost:8000/<uid>` (e.g. `http://localhost:8000/user01`).

### Running Tests

```bash
uv run --active pytest
```

## Docker Deployment

A production-ready Docker Compose setup with an Nginx reverse proxy is included.

```cmd
cd docker
build-amd64.cmd
docker-compose -f docker-compose.amd64.yml up -d
```

See [doc/DOCKER_DEPLOYMENT.md](doc/DOCKER_DEPLOYMENT.md) and [doc/DOCKER_QUICK_REFERENCE.md](doc/DOCKER_QUICK_REFERENCE.md) for full deployment and troubleshooting instructions.

## Key Endpoints

| Endpoint | Description |
|---|---|
| `GET /{uid}` | Web UI for the given user |
| `GET /send_email/{uid}` | Trigger an on-demand email digest |
| `GET /{uid}/clicktrack?lid=...&rating=...` | Record a click (positive/negative sample) |
| `POST /{uid}/save_negative_samples` | Bulk-record "marked as read" items as negative ML samples |
| `GET /{uid}/settings` | Merged runtime settings (config defaults + overlay) as JSON |
| `PUT /{uid}/settings` | Validate and persist per-user/global runtime settings |
| `POST /{uid}/refresh` | Trigger an immediate re-render (fetch + filter + dedup) |

## Settings (Runtime GUI)

NFM ships a small database-free settings GUI. The gear icon (⚙️) in the web UI opens an overlay that lets each user edit, without touching `config.py` or restarting:

- per-user: `highlight_keywords`, `blacklist_link`, `blacklist_title`, `recipients`, `consumption_modes`, `source_sort_order` and the full feed table (source/url/topic, optional `check_paywall`/`desc_filter`),
- global (advanced section): `LIMIT`, `HOURS_BACK`, `SOURCE_FILTER`, `CRONTRIGGER`, `ENABLE_HIDE_UNREAD`, `DEPLOY_MANIFEST`, the paywall thresholds and the ML settings.

Saving writes the changes through `PUT /{uid}/settings` into the `SettingsStore`, which merges them on top of the `config.py` defaults and persists the overlay to a JSON file:

```json
{
  "version": 1,
  "global": { "<GLOBAL_KEY>": value, ... },
  "users": { "<uid>": { "settings": {...}, "feeds": [...] } }
}
```

Global values are applied to the live `config` module immediately, so modules reading `config.XXX` at call time (paywall detector, ML tagger, feedmgr) pick them up on their next run. The settings GUI then triggers `POST /{uid}/refresh` so the changed settings take effect right away instead of waiting for the hourly job.

The overlay file defaults to `runtime-settings.json` relative to the process working directory (`config.RUNTIME_SETTINGS_FILE`). In container deployments point it at a persisted, bind-mounted path via the `NFM_RUNTIME_SETTINGS` environment variable, e.g.:

```bash
NFM_RUNTIME_SETTINGS=/data/nfm/runtime-settings.json
```

If the file is not writable at startup the effective configuration is still resolved in memory from `config.py`; persistence failures are logged, not fatal.

## Project Structure

``` txt
main.py                    # Production FastAPI app with scheduler
main_web_eval.py            # Dev server using precomputed render data
app/
  conf/                    # Configuration (users, feeds, ML/paywall settings)
  core/                    # Fetching, dedup, ML tagging, filtering, rendering
  web/                     # Static assets and Jinja2 templates
aux_data/                  # Stopwords used for TF-IDF pre-filtering
clicktrack/                # Per-user click history (JSONL) and trained ML models
docker/                    # Dockerfile, Compose files, build scripts
nginx/                     # Reverse proxy configuration
tests/                     # Test suite
```

## Notes

- **Automatic versioning:** The visible page version (footer `v…`) is resolved
  automatically on every build and stays traceable to a commit. The Docker
  build bakes `GIT_VERSION = $(git describe --tags --always --dirty)-<build-date>`
  into `/app/VERSION` (see `build/build.sh` and the Dockerfile `ARG`). `main.py`
  reads it at runtime with a fallback chain: VERSION file → `git describe`
  (dev checkouts) → pyproject.toml version + `-local`. No manual version bump
  needed.
- Optimized for low-resource deployment; uses a CPU-only PyTorch build and a small (~80MB) multilingual sentence-transformer model.
- German-language focus out of the box (stopwords, default keywords, news sources), but fully configurable for other languages via `app/conf/config.py`.
- `secrets/secrets.json`, click-tracking data, and trained ML models are git-ignored and machine/user-specific — never commit real credentials.

## License

This project is distributed under the MIT License. See [LICENSE.txt](LICENSE.txt).
