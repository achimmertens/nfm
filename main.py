# https://fastapi.tiangolo.com/tutorial/first-steps/#recap
# fastapi dev main.py --reload
# https://stackoverflow.com/questions/384076/how-can-i-color-python-logging-output

import asyncio
import tomllib
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

import app.conf.config as config
from app.core.feedmgr import NewsFeedManager
from app.core.loghandler import logger
import app.conf.logging_config as logging_config

# Read version from pyproject.toml
with open("pyproject.toml", "rb") as f:
    pyproject_data = tomllib.load(f)
    APP_VERSION = pyproject_data["project"]["version"]

# Initialize NewsFeedManager
nfm = NewsFeedManager(
    config.user_cfgs,
    limit=config.LIMIT,
    hours_back=config.HOURS_BACK
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
    
    # Run initial update
    logger.info("Running initial update")
    await update_render_data()
    
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
        #nfm_by_uid[uid].save_render_data_as_json(Path(f"render_data_{uid}.json"))
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
            },
        )
    else:
        logger.warning(f"index: uid {uid} not found")
        return "", 404  # Return empty response with 404 Not Found status


@app.get("/send_email/{uid}")
async def send_email(request: Request, uid: str):
    if uid in nfm.news_feed_users_by_uid:
        nfu = nfm.news_feed_users_by_uid[uid]
        
        # Skip if user does not consume via email
        if "email" not in nfu.consumption_modes:
            logger.debug(f"[{uid}] skipping email send; 'email' not in consumption_modes")
            return {"error": "User does not have email consumption mode enabled"}, 400
        
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, nfu.send_app_via_email)
        return {"message": "Email sent successfully"}
    else:
        logger.warning(f"send_email: uid {uid} not found")
        return {"error": "User not found"}, 404


@app.get("/{uid}/clicktrack")
async def clicktrack(uid: str, request: Request):
    lid = request.query_params.get('lid')
    rating = request.query_params.get('rating')
    nfu = nfm.get_news_feed_user(uid)
    if nfu:
        if nfu.clicktrack(lid, int(rating)):
            logger.info(f"[{uid}] clicktrack: lid {lid} recorded, rating={rating}")
        else:
            logger.warning(f"[{uid}] clicktrack: lid {lid} not found")
    else:
        logger.warning(f"[{uid}] clicktrack: uid {uid} not found")
    return "", 200  # Return empty response with 200 OK status


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
            return {"error": "User not found"}, 404
        
        count = nfu.save_negative_samples(lids, section_name, section_type)
        logger.info(f"[{uid}] save_negative_samples: {count} negative samples saved for {section_type} '{section_name}'")
        
        return {"message": f"{count} negative samples saved", "count": count}, 200
        
    except Exception as e:
        logger.exception(f"[{uid}] save_negative_samples: error processing request")
        return {"error": str(e)}, 500



if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_config=logging_config.LOGGING_CONFIG)