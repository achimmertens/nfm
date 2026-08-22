"""RSS feed processing with controlled concurrency."""
import asyncio
import aiohttp
from typing import List, Dict, Optional
from dataclasses import dataclass
import time
import random
import logging
import os

logger = logging.getLogger(__name__)

# Common user agents that RSS readers use
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
    'Feedbin feed-id:1 - 1 subscribers',
    'Feedly/1.0 (+http://www.feedly.com/fetcher.html; like FeedFetcher-Google)',
    'NewsBlur Feed Fetcher - 1 subscribers - https://newsblur.com',
]


@dataclass
class FeedResult:
    """Container for feed fetch results"""
    feed_url: str
    raw_content: Optional[str] = None
    error: Optional[str] = None
    status_code: Optional[int] = None
    retry_count: int = 0


async def _fetch_feed(
    session: aiohttp.ClientSession,
    feed_url: str,
    timeout: int = 30,
    max_retries: int = 3,
    proxy: Optional[str] = None
) -> FeedResult:
    """
    Fetch a single RSS feed asynchronously with retry logic.
    
    Args:
        session: aiohttp ClientSession for making requests
        feed_url: feed url to fetch
        timeout: Request timeout in seconds
        max_retries: Maximum number of retry attempts for failures
        proxy: HTTP proxy URL (e.g., 'http://proxy.example.com:8080')
    
    Returns:
        FeedResult object with raw content or error info
    """
    for attempt in range(max_retries):
        try:
            # Rotate user agents and add realistic headers
            headers = {
                'User-Agent': random.choice(USER_AGENTS),
                'Accept': 'application/rss+xml, application/xml, text/xml, application/atom+xml, */*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
                'Cache-Control': 'max-age=0',
            }
            
            # Add small random delay between retries
            if attempt > 0:
                await asyncio.sleep(random.uniform(1, 3))
            
            async with session.get(
                feed_url,
                timeout=aiohttp.ClientTimeout(total=timeout),
                headers=headers,
                allow_redirects=True,
                ssl=False,  # Some feeds have SSL issues
                proxy=proxy
            ) as response:
                if response.status == 200:
                    content = await response.text()
                    return FeedResult(
                        feed_url=feed_url,
                        raw_content=content,
                        status_code=response.status,
                        retry_count=attempt
                    )
                elif response.status == 403 and attempt < max_retries - 1:
                    # Retry 403 errors with different user agent
                    continue
                else:
                    return FeedResult(
                        feed_url=feed_url,
                        error=f"HTTP {response.status}",
                        status_code=response.status,
                        retry_count=attempt
                    )
        except asyncio.TimeoutError:
            if attempt < max_retries - 1:
                continue
            return FeedResult(
                feed_url=feed_url,
                error="Timeout",
                retry_count=attempt
            )
        except Exception as e:
            if attempt < max_retries - 1:
                continue
            return FeedResult(
                feed_url=feed_url,
                error=str(e),
                retry_count=attempt
            )
    
    # Should not reach here, but just in case
    return FeedResult(
        feed_url=feed_url,
        error="Max retries exceeded",
        retry_count=max_retries
    )


async def _fetch_all_feeds(
    rss_feed_pool: List[Dict[str, any]],
    max_concurrent: int = 10,
    timeout: int = 30,
    max_retries: int = 3
) -> List[FeedResult]:
    """
    Fetch all RSS feeds with controlled concurrency.
    
    Args:
        rss_feed_pool: List of feed urls
        max_concurrent: Maximum number of concurrent requests
        timeout: Request timeout in seconds
        max_retries: Maximum retry attempts per feed
    
    Returns:
        List of FeedResult objects
    """
    # Create semaphore to limit concurrent requests
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def fetch_with_semaphore(session, feed_url):
        async with semaphore:
            return await _fetch_feed(session, feed_url, timeout, max_retries, proxy)
    
    # Get proxy from environment variable if set
    proxy = os.environ.get('HTTP_PROXY') or os.environ.get('http_proxy')
    if proxy:
        logger.info(f"Using HTTP proxy: {proxy}")
    
    # Configure aiohttp session with connection pooling
    connector = aiohttp.TCPConnector(
        limit=max_concurrent,
        limit_per_host=5,
        ttl_dns_cache=300,
        ssl=False  # Disable SSL verification for problematic feeds
    )
    
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [
            fetch_with_semaphore(session, feed_url)
            for feed_url in rss_feed_pool
        ]
        results = await asyncio.gather(*tasks)
    
    return results


def process_feeds(rss_feed_pool: List[Dict[str, any]], uid: str) -> Dict[str, any]:
    """
    Main function to process all feeds and return results with statistics.
    
    Args:
        rss_feed_pool: List of feed urls
        uid: User identifier
    
    Returns:
        Dictionary containing results and statistics
    """
    start_time = time.time()
    
    # Run async fetching
    results = asyncio.run(_fetch_all_feeds(rss_feed_pool))
    
    # Separate successful and failed fetches
    successful = [r for r in results if r.raw_content is not None]
    successful_by_url = {r.feed_url: r for r in successful}
    failed = [r for r in results if r.raw_content is None]
    
    elapsed_time = time.time() - start_time
    
    # Log statistics
    logger.info(f"[{uid}] RSS Feed Fetch Complete - Total feeds: {len(results)}, Successful: {len(successful)}, Failed: {len(failed)}")
    if len(results) > 0:
        logger.info(f"[{uid}] Time elapsed: {elapsed_time:.2f}s, Average time per feed: {elapsed_time/len(results):.2f}s")
    
    if failed:
        error_types = {}
        logger.info(f"[{uid}] Failed Feeds:")
        for result in failed:
            logger.info(f"[{uid}] ERR: {result.error} (retries: {result.retry_count}), URL: {result.feed_url}")
            error_key = result.error.split()[0] if result.error else "Unknown"
            error_types[error_key] = error_types.get(error_key, 0) + 1
        
        # Show breakdown of error types
        logger.info(f"[{uid}] Error Breakdown:")
        for error_type, count in sorted(error_types.items(), key=lambda x: x[1], reverse=True):
            logger.info(f"[{uid}] {error_type}: {count}")
    
    return {
        'results': results,
        'successful': successful,
        'successful_by_url': successful_by_url,
        'failed': failed,
        'stats': {
            'total': len(results),
            'successful_count': len(successful),
            'failed_count': len(failed),
            'elapsed_time': elapsed_time
        }
    }
