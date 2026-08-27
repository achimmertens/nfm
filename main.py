# https://fastapi.tiangolo.com/tutorial/first-steps/#recap
# fastapi dev main.py --reload
# https://stackoverflow.com/questions/384076/how-can-i-color-python-logging-output

import asyncio
import importlib
import subprocess
import tomllib
import uvicorn
from pathlib import Path
from copy import deepcopy
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

import app.conf.config as config
from app.core.feedmgr import NewsFeedManager
from app.core.loghandler import logger
from app.core.settings_store import SettingsStore, GLOBAL_KEYS
import app.conf.logging_config as logging_config

# --- Automatic version resolution ---
# The visible app version is resolved automatically with a robust fallback
# chain so it stays traceable to the exact commit on every build without
# manual version bumps in pyproject.toml:
#   1. A build-time-baked VERSION file (written by the Docker build via the
#      GIT_VERSION build-arg -> /app/VERSION). Primary source in the image.
#   2. `git describe --tags --always --dirty` (only when .git + git are
#      present, e.g. when running straight from a repo checkout / dev mode).
#   3. pyproject.toml version + "-local" marker as a last-resort fallback.
# Never crashes if git/VERSION are unavailable.
_VERSION_FILE = Path("/app/VERSION")


def _read_version_file() -> str | None:
    """Read the build-time-baked VERSION file if present."""
    try:
        if _VERSION_FILE.exists():
            v = _VERSION_FILE.read_text().strip()
            if v:
                return v
    except OSError:
        pass
    return None


def _read_git_version() -> str | None:
    """Best-effort `git describe`; None when git or .git is missing."""
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode == 0:
            v = result.stdout.strip()
            if v:
                return v
    except Exception:
        pass
    return None


def _read_pyproject_version() -> str:
    with open("pyproject.toml", "rb") as f:
        return tomllib.load(f)["project"]["version"]


APP_VERSION = (
    _read_version_file()
    or _read_git_version()
    or f"{_read_pyproject_version()}-local"
)

# Runtime settings store: overlays config.py defaults with the contents of
# runtime-settings.json (path via config.RUNTIME_SETTINGS_FILE or the
# NFM_RUNTIME_SETTINGS env var) and persists per-user/global edits made through
# the settings GUI (GET/PUT /{uid}/settings). Instantiated here (module import
# == app start) and handed to the NewsFeedManager, whose NewsFeedUser instances
# read filter/feed values live from the store on every render cycle.
settings_store = SettingsStore()

# Initialize NewsFeedManager
nfm = NewsFeedManager(
    config.user_cfgs,
    limit=config.LIMIT,
    hours_back=config.HOURS_BACK,
    settings_store=settings_store,
)


# Scheduler instance
scheduler = AsyncIOScheduler()


async def update_render_data():
    """Run blocking update operations in thread pool"""
    logger.info("Starting periodic update of render data")
    
    try:
        # Get the event loop
        loop = asyncio.get_event_loop()
        
        # Run blocking operations in executor (thread pool)
        for uid, nfu in nfm.news_feed_users_by_uid.items():
            # Skip if user does not consume via web
            if "web" not in nfu.consumption_modes:
                logger.debug(f"[{uid}] skipping render data update; 'web' not in consumption_modes")
                continue

            logger.info(f"Updating render data for {uid}")

            # This runs the blocking operation in a separate thread
            await loop.run_in_executor(None, nfu.update_render_data)
        
        logger.info("Periodic update completed successfully")
    except Exception:
        logger.exception("Error during periodic update")


def _background_initial_render():
    """Run the initial render for all web users without blocking FastAPI startup.

    Launched as a background asyncio task so the HTTP server becomes available
    immediately; the frontend polls /render_status to show a progress banner
    while feeds are analysed, and each NewsFeedUser publishes partial results
    as it goes.
    """
    loop = asyncio.get_event_loop()
    loop.create_task(update_render_data())


async def send_app_via_email():
    """Send email with news feed data"""
    logger.info("Starting email sending process")
    
    try:

        # Get the event loop
        loop = asyncio.get_event_loop()
        
        # Send app via email for each user
        for uid, nfu in nfm.news_feed_users_by_uid.items():
            # Skip if user does not consume via email
            if "email" not in nfu.consumption_modes:
                logger.debug(f"[{uid}] skipping email send; 'email' not in consumption_modes")
                continue
                
            logger.info(f"Sending app via email for {uid}")
            
            # Send email in thread pool (blocking operation)
            await loop.run_in_executor(None, nfu.send_app_via_email)

    except Exception:
        logger.exception("Error during app sending")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan"""
    # Startup
    logger.info("Application startup: initializing scheduler")

    # Re-read the runtime settings file (if present) so that edits made while
    # the process was stopped are picked up. Idempotent: merges on top of the
    # config.py defaults again.
    settings_store.load()

    # Add the periodic job for updating render data
    scheduler.add_job(
        update_render_data,
        trigger=IntervalTrigger(hours=1),
        id="update_render_data",
        name="Update render data hourly",
        replace_existing=True,
        max_instances=1,  # Prevent overlapping executions
    )
    
    # Add the daily email job
    scheduler.add_job(
        send_app_via_email,
        trigger=CronTrigger(
            hour=config.CRONTRIGGER["hour"],
            minute=config.CRONTRIGGER["minute"],
            timezone="Europe/Berlin"
        ),
        id="send_app_via_email",
        name=f"Send app via email daily at {config.CRONTRIGGER['hour']}:{config.CRONTRIGGER['minute']}",
        replace_existing=True,
        max_instances=1,  # Prevent overlapping executions
    )
    
    # Start the scheduler
    scheduler.start()
    logger.info("Scheduler started")
    
    # Run initial update in the background so the server stays responsive;
    # the frontend shows a progress banner while feeds are analysed.
    logger.info("Running initial update (background)")
    _background_initial_render()
    
    yield
    
    # Shutdown
    logger.info("Application shutdown: stopping scheduler")
    scheduler.shutdown(wait=True)
    logger.info("Scheduler stopped")


app = FastAPI(title="NFM", lifespan=lifespan)


app.mount("/static", StaticFiles(directory="app/web/static"), name="static")
templates = Jinja2Templates(directory="app/web/templates")


@app.get("/favicon.ico")
async def favicon():
    return FileResponse("app/web/static/favicon.ico")


@app.get("/{uid}", response_class=HTMLResponse)
async def root(request: Request, uid: str, limit: int = 10, hours_back: int = 24):
    if uid in nfm.news_feed_users_by_uid:
        nfu = nfm.news_feed_users_by_uid[uid]
        data = nfu.render_data
        uninteresting_lids = nfu.get_uninteresting_lids()
        return templates.TemplateResponse(
            request=request,
            name="nfm.jinja",
            context={
                "data": data,
                "enable_hide_unread": config.ENABLE_HIDE_UNREAD,
                "deploy_manifest": config.DEPLOY_MANIFEST,
                "app_version": APP_VERSION,
                "uninteresting_lids": uninteresting_lids,
                "show_settings_ui": True,
            },
        )
    else:
        logger.warning(f"index: uid {uid} not found")
        # Explicit Response instead of a (content, status) tuple: FastAPI does
        # not unpack tuples into (content, status_code) on this route, it would
        # serialize the tuple as a JSON list and crash HTMLResponse.encode().
        return Response(content="", status_code=404)


@app.get("/{uid}/render_status")
async def render_status(uid: str):
    """Return the current render progress for the frontend banner."""
    nfu = nfm.get_news_feed_user(uid)
    if not nfu:
        logger.warning(f"render_status: uid {uid} not found")
        return JSONResponse({"error": "User not found"}, status_code=404)
    return JSONResponse(nfu.render_status)


@app.get("/send_email/{uid}")
async def send_email(request: Request, uid: str):
    if uid in nfm.news_feed_users_by_uid:
        nfu = nfm.news_feed_users_by_uid[uid]
        
        # Skip if user does not consume via email
        if "email" not in nfu.consumption_modes:
            logger.debug(f"[{uid}] skipping email send; 'email' not in consumption_modes")
            return JSONResponse({"error": "User does not have email consumption mode enabled"}, status_code=400)
        
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, nfu.send_app_via_email)
        return {"message": "Email sent successfully"}
    else:
        logger.warning(f"send_email: uid {uid} not found")
        return JSONResponse({"error": "User not found"}, status_code=404)


@app.get("/{uid}/clicktrack")
async def clicktrack(uid: str, request: Request):
    lid = request.query_params.get('lid')
    rating = request.query_params.get('rating')
    stars = request.query_params.get('stars', '3')
    nfu = nfm.get_news_feed_user(uid)
    if nfu:
        try:
            stars_i = int(stars)
        except (TypeError, ValueError):
            stars_i = 3
        if nfu.clicktrack(lid, int(rating), stars=stars_i):
            logger.info(f"[{uid}] clicktrack: lid {lid} recorded, rating={rating}, stars={stars_i}")
        else:
            logger.warning(f"[{uid}] clicktrack: lid {lid} not found")
    else:
        logger.warning(f"[{uid}] clicktrack: uid {uid} not found")
    return Response(content="", status_code=200)  # Empty 200 OK response


@app.post("/{uid}/save_negative_samples")
async def save_negative_samples(uid: str, request: Request):
    """Save negative samples (unread items) for ML training."""
    try:
        data = await request.json()
        lids = data.get('lids', [])
        section_name = data.get('section_name', '')
        section_type = data.get('section_type', '')
        
        nfu = nfm.get_news_feed_user(uid)
        if not nfu:
            logger.warning(f"[{uid}] save_negative_samples: uid not found")
            return JSONResponse({"error": "User not found"}, status_code=404)
        
        count = nfu.save_negative_samples(lids, section_name, section_type)
        logger.info(f"[{uid}] save_negative_samples: {count} negative samples saved for {section_type} '{section_name}'")
        
        return JSONResponse({"message": f"{count} negative samples saved", "count": count}, status_code=200)
        
    except Exception as e:
        logger.exception(f"[{uid}] save_negative_samples: error processing request")
        return JSONResponse({"error": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# Settings API
# ---------------------------------------------------------------------------
# Per-user setting keys accepted by PUT /{uid}/settings, and their expected
# JSON types. Unknown keys in the "settings" block are rejected (422).
_STRING_LIST_KEYS = (
    "blacklist_link",
    "blacklist_title",
    "highlight_keywords",
    "recipients",
    "consumption_modes",
)
_SORT_ORDER_KEY = "source_sort_order"

# Global keys exposed to the settings GUI and their expected JSON types.
# "int"      -> integer (not bool)
# "number"   -> int or float (not bool)
# "bool"     -> boolean
# "strlist"  -> list of strings
# "cron"     -> {"hour": "HH", "minute": "MM"} (strings)
_GLOBAL_VALIDATORS = {
    "LIMIT": "int",
    "HOURS_BACK": "int",
    "SOURCE_FILTER": "strlist",
    "CRONTRIGGER": "cron",
    "ENABLE_HIDE_UNREAD": "bool",
    "DEPLOY_MANIFEST": "bool",
    "PAYWALL_SCORE_THRESHOLD": "int",
    "PAYWALL_REQUEST_TIMEOUT_SECONDS": "int",
    "PAYWALL_REQUEST_RETRIES": "int",
    "ML_TAG_ENABLED": "bool",
    "ML_TAG_THRESHOLD": "number",
    "ML_RETRAIN_THRESHOLD_BYTES": "int",
    "ML_NEGATIVE_WEIGHT": "number",
    "ML_NEGATIVE_CAP_MULTIPLIER": "number",
}


async def _request_json(request: Request):
    """Parse a JSON request body; return (data, error_message)."""
    try:
        return await request.json(), None
    except Exception:
        return None, "Request body must be valid JSON"


def _validate_string_list(value, errs, path):
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        errs.append(f"{path}: must be a list of strings")


def _validate_settings_block(settings, uid, errs):
    """Strictly validate the "settings" block of a PUT /{uid}/settings body."""
    if not isinstance(settings, dict):
        errs.append("settings: must be an object")
        return
    for key, value in settings.items():
        if key == "uid":
            if value != uid:
                errs.append("settings.uid: must match the uid in the URL path")
            continue
        if key in _STRING_LIST_KEYS:
            _validate_string_list(value, errs, f"settings.{key}")
        elif key == _SORT_ORDER_KEY:
            if not isinstance(value, dict) or not all(
                isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool)
                for k, v in value.items()
            ):
                errs.append(
                    f"settings.{key}: must be an object mapping source name -> integer"
                )
        else:
            errs.append(f"settings.{key}: unknown setting key")


def _validate_feed(feed, idx, errs):
    """Strictly validate one entry of the "feeds" list."""
    if not isinstance(feed, dict):
        errs.append(f"feeds[{idx}]: must be an object")
        return
    for req in ("source", "url", "topic"):
        value = feed.get(req)
        if not isinstance(value, str) or not value.strip():
            errs.append(f"feeds[{idx}].{req}: required non-empty string")
    if "check_paywall" in feed and not isinstance(feed["check_paywall"], bool):
        errs.append(f"feeds[{idx}].check_paywall: must be a boolean")
    if "desc_filter" in feed and not isinstance(feed["desc_filter"], str):
        errs.append(f"feeds[{idx}].desc_filter: must be a string")
    if "description" in feed and not isinstance(feed["description"], str):
        errs.append(f"feeds[{idx}].description: must be a string")
    for key in feed:
        if key not in ("source", "url", "topic", "check_paywall", "desc_filter", "description"):
            errs.append(f"feeds[{idx}].{key}: unknown feed key")


def _validate_global_block(global_, errs):
    """Strictly validate the optional "global" block of a PUT body."""
    if not isinstance(global_, dict):
        errs.append("global: must be an object")
        return
    for key, value in global_.items():
        if key not in GLOBAL_KEYS:
            errs.append(f"global.{key}: unknown global key")
            continue
        kind = _GLOBAL_VALIDATORS.get(key)
        if kind == "int":
            if not isinstance(value, int) or isinstance(value, bool):
                errs.append(f"global.{key}: must be an integer")
        elif kind == "number":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                errs.append(f"global.{key}: must be a number")
        elif kind == "bool":
            if not isinstance(value, bool):
                errs.append(f"global.{key}: must be a boolean")
        elif kind == "strlist":
            _validate_string_list(value, errs, f"global.{key}")
        elif kind == "cron":
            if not isinstance(value, dict):
                errs.append(f"global.{key}: must be an object with 'hour' and 'minute'")
            else:
                h, m = value.get("hour"), value.get("minute")
                if not isinstance(h, str) or not isinstance(m, str) or not h.strip() or not m.strip():
                    errs.append(
                        f"global.{key}: 'hour' and 'minute' must be non-empty strings"
                    )


def _settings_payload(uid: str):
    """Merged settings payload for the settings GUI, or None if uid unknown."""
    user = settings_store.get_user(uid)
    if user is None:
        return None
    settings = user.get("settings", {})
    payload = {
        "uid": uid,
        "settings": settings,
        "feeds": user.get("feeds", []),
    }
    if _SORT_ORDER_KEY in settings:
        payload[_SORT_ORDER_KEY] = settings[_SORT_ORDER_KEY]
    payload["global"] = settings_store.get_global()
    return payload


@app.get("/{uid}/settings")
async def get_settings(uid: str):
    """Return the merged (defaults + runtime overlay) settings for a user."""
    payload = _settings_payload(uid)
    if payload is None:
        logger.warning(f"get_settings: uid {uid} not found")
        return JSONResponse({"error": "User not found"}, status_code=404)
    return JSONResponse(payload)


@app.put("/{uid}/settings")
async def put_settings(uid: str, request: Request):
    """Validate and persist settings for a user.

    Body (all fields optional, at least one expected):
        {
          "settings": {  # keys from USER_SETTING_KEYS, strictly typed
            "blacklist_link": [...], "blacklist_title": [...],
            "highlight_keywords": [...], "recipients": [...],
            "consumption_modes": [...], "source_sort_order": {src: int}
          },
          "feeds": [{source, url, topic, check_paywall?, desc_filter?}],
          "global": {LIMIT?, HOURS_BACK?, ...}  # optional, applied immediately
        }
    Invalid payloads are rejected with 422 and nothing is persisted.
    """
    if uid not in nfm.news_feed_users_by_uid:
        logger.warning(f"put_settings: uid {uid} not found")
        return JSONResponse({"error": "User not found"}, status_code=404)

    body, err = await _request_json(request)
    if err:
        return JSONResponse({"error": err}, status_code=422)
    if not isinstance(body, dict):
        return JSONResponse({"error": "Body must be a JSON object"}, status_code=422)

    errs = []
    settings = body.get("settings")
    feeds = body.get("feeds")
    global_ = body.get("global")

    if settings is not None:
        _validate_settings_block(settings, uid, errs)
    if feeds is not None:
        if not isinstance(feeds, list):
            errs.append("feeds: must be a list")
        else:
            for idx, feed in enumerate(feeds):
                _validate_feed(feed, idx, errs)
    if global_ is not None:
        _validate_global_block(global_, errs)

    if errs:
        return JSONResponse({"error": "Validation failed", "details": errs}, status_code=422)

    if not settings_store.update_user(
        uid, settings=settings, feeds=feeds, global_=global_
    ):
        logger.warning(f"put_settings: store rejected uid {uid}")
        return JSONResponse({"error": "User not found"}, status_code=404)

    logger.info(f"[{uid}] settings updated via API")
    return JSONResponse({"message": "Settings saved", "uid": uid})


@app.post("/{uid}/refresh")
async def refresh_uid(uid: str):
    """Trigger an immediate re-render for a user (fetch feeds + filters + dedup).

    Called by the settings GUI after a successful PUT so that changed settings
    take effect right away instead of waiting for the hourly scheduled job.
    """
    nfu = nfm.get_news_feed_user(uid)
    if not nfu:
        logger.warning(f"refresh: uid {uid} not found")
        return JSONResponse({"error": "User not found"}, status_code=404)
    logger.info(f"[{uid}] manual refresh triggered")
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, nfu.update_render_data)
    return JSONResponse({"message": "Render data refreshed", "uid": uid})


@app.post("/{uid}/reload")
async def reload_uid(uid: str):
    """Reload config.py at runtime and rebuild the feed manager.

    Unlike /refresh (which only re-renders the existing feeds), this endpoint
    re-imports the config module so newly added portals in config.py become
    effective without a container restart. config.py becomes the authoritative
    source for the feed list, while the other runtime settings (blacklist,
    highlight keywords, sort order, recipients) are preserved. The updated feed
    list is persisted to the runtime settings file so a later restart stays
    consistent.
    """
    global settings_store, nfm
    try:
        reloaded = importlib.reload(config)
    except Exception:
        logger.exception("[{}] reload: failed to re-import config.py".format(uid))
        return JSONResponse({"error": "Failed to reload config.py"}, status_code=500)

    try:
        # 1. Rebuild the store from the fresh config defaults. load() overlays
        #    the runtime file, which may carry a stale feed list.
        new_store = SettingsStore(user_cfgs=reloaded.user_cfgs)

        # 2. config.py is authoritative for the feed list -> re-assert its feeds
        #    for every known user (keeps blacklist/keywords/sort/recipients).
        for ucfg in reloaded.user_cfgs or []:
            suid = (ucfg.get("settings") or {}).get("uid")
            if not suid:
                continue
            if suid in new_store._user_by_uid:
                new_store._user_by_uid[suid]["feeds"] = deepcopy(ucfg.get("feeds") or [])

        # 3. Persist so that a later restart keeps the config.py feed list.
        new_store.save()

        # 4. Rebuild the manager against the fresh config + store.
        new_nfm = NewsFeedManager(
            reloaded.user_cfgs,
            limit=reloaded.LIMIT,
            hours_back=reloaded.HOURS_BACK,
            settings_store=new_store,
        )
        settings_store = new_store
        nfm = new_nfm

        # 5. Re-render the requested user (and web consumers) immediately.
        loop = asyncio.get_event_loop()
        nfu = nfm.get_news_feed_user(uid)
        if nfu:
            await loop.run_in_executor(None, nfu.update_render_data)
            logger.info("[{}] config reloaded and re-rendered".format(uid))
        return {"message": "Config reloaded", "uid": uid}
    except Exception:
        logger.exception("[{}] reload rebuild failed".format(uid))
        return JSONResponse({"error": "Reload rebuild failed"}, status_code=500)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_config=logging_config.LOGGING_CONFIG)