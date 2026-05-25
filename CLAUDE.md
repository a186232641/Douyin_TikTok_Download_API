# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Async scraping service for Douyin / TikTok / Bilibili exposing two interfaces from the same FastAPI process:

- A REST API under `/api/...` (Swagger at `/docs`, ReDoc at `/redoc`)
- A PyWebIO web UI mounted at `/` (only when `Web.PyWebIO_Enable` is true in `config.yaml`)

Both surfaces sit on top of HTTPX-based platform crawlers in `crawlers/`. There is no test suite, build step, or linter configured — running the app and hitting endpoints is the development feedback loop.

## Running the app

```bash
pip install -r requirements.txt
python3 start.py          # uvicorn with reload, reads host/port from ./config.yaml
```

`start.py` calls `uvicorn.run('app.main:app', ...)`. The default `Host_Port` in `config.yaml` is `80` — change it before running locally if you don't have privileges for that port.

Docker:

```bash
docker build -t douyin_tiktok_download_api .
docker compose up        # uses host network mode; volume-mounts crawler config files
```

Production deploy (Linux): `bash/install.sh` clones to `/www/wwwroot/Douyin_TikTok_Download_API`, creates a venv, and installs `daemon/Douyin_TikTok_Download_API.service` as a systemd unit. `bash/update.sh` pulls and restarts that service.

## Configuration model — important

There are **multiple `config.yaml` files**, each scoped to a different layer. Editing the wrong one is a common source of confusion:

| File | Controls |
|------|----------|
| `./config.yaml` | API host/port, version string shown in docs, PyWebIO theme/toggle, `Download_Switch`, download path/prefix |
| `crawlers/douyin/web/config.yaml` | Douyin headers (**including the Cookie that must be refreshed from a browser**), msToken, ttwid, X-Bogus/A_Bogus parameters |
| `crawlers/tiktok/web/config.yaml` | TikTok Web headers, msToken, X-Bogus parameters |
| `crawlers/tiktok/app/config.yaml` | TikTok App-API parameters (device info, version codes) |
| `crawlers/bilibili/web/config.yaml` | Bilibili Web headers/cookies |

Each platform module reads **its own** `config.yaml` at import time using `os.path.dirname(__file__)`, not the root config. When Douyin requests start failing with empty bodies or 4xx, the fix is almost always updating the `Cookie` in `crawlers/douyin/web/config.yaml` with a fresh cookie from a logged-in browser. Don't change the `User-Agent` in those crawler configs — Douyin's risk control is keyed to specific UAs.

`config.yaml` flags worth knowing:

- `API.Download_Switch` — when `false`, the `/api/download` endpoint short-circuits with an error response. Demo deployments keep this off.
- `Web.PyWebIO_Enable` — when `false`, only the FastAPI routes are served (no UI mount at `/`).

## Architecture

### Two-tier layout: `app/` (HTTP surfaces) sits on top of `crawlers/` (scraping engines)

```
app/main.py            FastAPI app; loads root config.yaml; mounts api_router under /api;
                       conditionally mounts PyWebIO MainView at /
app/api/router.py      Aggregates the per-platform routers
app/api/endpoints/     One file per platform/feature (douyin_web, tiktok_web, tiktok_app,
                       bilibili_web, hybrid_parsing, download, ios_shortcut)
app/api/models/        Pydantic response models
app/web/app.py         PyWebIO MainView (selectable functions: batch parse, easter egg, ...)
app/web/views/         Per-page PyWebIO pop-up windows (ParseVideo, Downloader, etc.)

crawlers/base_crawler.py        BaseCrawler — async httpx client with retry / connection-limit /
                                semaphore / HTTP-status → APIError mapping. All platform crawlers
                                construct one of these per call inside `async with`.
crawlers/utils/                 Shared logger, api_exceptions, common helpers
crawlers/douyin/web/            DouyinWebCrawler + endpoints/models/utils + xbogus.py / abogus.py
                                (request-signing algorithms — keep `User-Agent` aligned with these)
crawlers/tiktok/web/            TikTokWebCrawler (similar layout, no a_bogus)
crawlers/tiktok/app/            TikTokAPPCrawler (uses unsigned mobile-app endpoints)
crawlers/bilibili/web/          BilibiliWebCrawler + wrid.py signing
crawlers/hybrid/hybrid_crawler.py
                                HybridCrawler — sniffs `douyin`/`tiktok` in the URL, calls the
                                matching platform crawler, then normalizes the result. For TikTok
                                it routes to TikTokAPPCrawler (not the Web one — see comment at
                                hybrid_crawler.py:61).
```

### Per-platform crawler pattern

Each crawler method follows the same shape:

1. Read the platform's `config.yaml` for headers + proxies.
2. Instantiate a fresh `BaseCrawler` inside `async with` (this is per-request, not shared).
3. Build a Pydantic params model from `crawlers/<platform>/web/models.py`.
4. Sign the URL via the platform's bogus/wrid utility (`BogusManager.ab_model_2_endpoint`, etc.) using endpoints from `crawlers/<platform>/web/endpoints.py`.
5. `await crawler.fetch_get_json(endpoint)` and return the raw dict.

When adding a new endpoint: add the URL constant to `endpoints.py`, the params shape to `models.py`, the crawler method to `web_crawler.py`, then expose it in `app/api/endpoints/<platform>_web.py` and tag it in `app/api/router.py`.

### Hybrid + download flow

`/api/hybrid/video_data` and `/api/download` both go through `HybridCrawler.hybrid_parsing_single_video`. `minimal=True` collapses the raw platform payload into a normalized `{platform, aweme_id, type, video_data | image_data, ...}` shape; `download.py` consumes that minimal form and streams the file via httpx, deleting partial files on client disconnect.

### Error model

`crawlers/utils/api_exceptions.py` defines an `APIError` hierarchy (`APIConnectionError`, `APIResponseError`, `APITimeoutError`, `APIUnavailableError`, `APIUnauthorizedError`, `APINotFoundError`, `APIRateLimitError`, `APIRetryExhaustedError`). `BaseCrawler.handle_http_status_error` maps HTTP status codes to these. Endpoint handlers catch broadly and return `ErrorResponseModel` from `app/api/models/APIResponseModel.py`.

## Notes for changes

- The Douyin `Cookie` in `crawlers/douyin/web/config.yaml` is committed and goes stale; treat refreshes as routine config maintenance, not code changes.
- `Host_Port: 80` in root `config.yaml` means non-root local runs will fail to bind — pick a high port for dev.
- `app/main.py` mounts PyWebIO at `/` **after** the API router. If you add new top-level routes, register them before the PyWebIO mount or they will be shadowed.
- The PyPI package `douyin-tiktok-scraper` referenced in the README is described as deprecated/needs-update; the repo itself is the source of truth.
