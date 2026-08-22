import logging
import zlib
import pytz
import aiohttp
import asyncio
import smtplib
import json
import re
from html import escape

from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Dict, Optional
from datetime import datetime, timedelta

import app.conf.config as config
import app.core.filter as filter_module

logger = logging.getLogger(__name__)


_PAYWALL_JSONLD_FALSE_RE = re.compile(
    r'"isaccessibleforfree"\s*:\s*(false|"false")',
    re.IGNORECASE,
)

_PAYWALL_JSONLD_TRUE_RE = re.compile(
    r'"isaccessibleforfree"\s*:\s*(true|"true")',
    re.IGNORECASE,
)

_HTML_COMMENT_RE = re.compile(r'<!--.*?-->', re.DOTALL)

# Strong publisher-agnostic signals that often indicate hard/metered paywalls.
_PAYWALL_STRONG_PATTERNS = [
    re.compile(r'\bmetered\s*paywall\b', re.IGNORECASE),
    re.compile(r'\bbehind\s+(?:a\s+)?paywall\b', re.IGNORECASE),
    re.compile(r'\bsubscriber\s*-?\s*only\b', re.IGNORECASE),
    re.compile(r'\bexklusiv\s+f(?:u|ue|ü)r\s+abonnent(?:en)?\b', re.IGNORECASE),
    re.compile(r'\bder\s+rest\s+ist\s+f(?:u|ue|ü)r\s+abonnent(?:en)?\b', re.IGNORECASE),
    re.compile(r'\bjetzt\s+abo\s+abschlie(?:s|ss|ß)en\b', re.IGNORECASE),
    re.compile(r'\babonnent(?:en)?\+\b', re.IGNORECASE),
    re.compile(r'\b(abo|abonnement)\s*(erforderlich|notwendig)\b', re.IGNORECASE),
    re.compile(r'\bnur\s+f(?:u|ue)r\s+abonnent(?:en)?\b', re.IGNORECASE),
    re.compile(
        r'\b(?:jetzt\s+)?abonnieren\b[\s\S]{0,80}\b(?:weiterlesen|weiterzulesen|'
        r'vollst(?:a|ae)ndigen\s+artikel\s+lesen|zugriff)\b',
        re.IGNORECASE,
    ),
    re.compile(r'\b(piano\.io|tinypass|cxense|poool|laterpay)\b', re.IGNORECASE),
    # GDPR consent-wall / PUR-Abo model (Der Standard, Spiegel, etc.)
    re.compile(r'\bmit\s+werbung\s+weiterlesen\b', re.IGNORECASE),
    re.compile(r'\bPUR\s*-?\s*Abo\b', re.IGNORECASE),
]

# Weaker textual hints. These require multiple matches to classify as paywalled.
_PAYWALL_WEAK_PATTERNS = [
    re.compile(r'\bmit\s+abo\b', re.IGNORECASE),
    re.compile(r'\bplus-?artikel\b', re.IGNORECASE),
    re.compile(r'\bvollst(?:a|ae)ndigen\s+artikel\s+lesen\b', re.IGNORECASE),
    re.compile(r'\bweiterlesen\s+mit\s+abo\b', re.IGNORECASE),
    re.compile(r'\bmember\s+only\b', re.IGNORECASE),
]

# Free-access hints to reduce false positives.
_PAYWALL_FREE_HINT_PATTERNS = [
    re.compile(r'"isaccessibleforfree"\s*:\s*(true|"true")', re.IGNORECASE),
    re.compile(r'\bkostenlos\b', re.IGNORECASE),
    re.compile(r'\bfree\s+article\b', re.IGNORECASE),
]


def _extract_jsonld_scripts(html_text: str) -> List[str]:
    """Extract candidate JSON-LD script payloads from HTML."""
    script_pattern = re.compile(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        re.IGNORECASE | re.DOTALL,
    )
    return [match.group(1).strip() for match in script_pattern.finditer(html_text)]


def _iter_json_nodes(node):
    """Yield nested dict nodes from arbitrary JSON structures."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _iter_json_nodes(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_json_nodes(item)


def _jsonld_accessibility_signal(html_text: str) -> tuple[int, List[str]]:
    """Return weighted signal score and reasons based on JSON-LD accessibility fields."""
    score = 0
    reasons: List[str] = []

    for payload in _extract_jsonld_scripts(html_text):
        candidate_nodes = []
        try:
            parsed = json.loads(payload)
            candidate_nodes.append(parsed)
        except json.JSONDecodeError:
            # Some publishers concatenate JSON objects in one script block.
            if _PAYWALL_JSONLD_FALSE_RE.search(payload):
                score += 90
                reasons.append("jsonld:isaccessibleforfree=false")
            if _PAYWALL_JSONLD_TRUE_RE.search(payload):
                score -= 40
                reasons.append("jsonld:isaccessibleforfree=true")
            continue

        for root in candidate_nodes:
            for obj in _iter_json_nodes(root):
                for key, value in obj.items():
                    if str(key).lower() != "isaccessibleforfree":
                        continue
                    value_str = str(value).strip().lower()
                    if value_str in {"false", "0", "no"}:
                        score += 90
                        reasons.append("jsonld:isaccessibleforfree=false")
                    elif value_str in {"true", "1", "yes"}:
                        score -= 40
                        reasons.append("jsonld:isaccessibleforfree=true")

    return score, reasons


def _heuristic_paywall_signal(html_text: str) -> tuple[int, List[str]]:
    """Return weighted signal score and reasons from textual markers."""
    score = 0
    reasons: List[str] = []
    text_without_comments = _HTML_COMMENT_RE.sub(" ", html_text)

    strong_hits = 0
    for pattern in _PAYWALL_STRONG_PATTERNS:
        if pattern.search(text_without_comments):
            strong_hits += 1
            reasons.append(f"strong:{pattern.pattern}")

    weak_hits = 0
    for pattern in _PAYWALL_WEAK_PATTERNS:
        if pattern.search(text_without_comments):
            weak_hits += 1
            reasons.append(f"weak:{pattern.pattern}")

    free_hits = 0
    for pattern in _PAYWALL_FREE_HINT_PATTERNS:
        if pattern.search(text_without_comments):
            free_hits += 1
            reasons.append(f"free_hint:{pattern.pattern}")

    score += min(strong_hits, 3) * 30
    if weak_hits >= 2:
        score += min(weak_hits, 4) * 10
    score -= min(free_hits, 2) * 15

    return score, reasons


def _is_paywalled_by_signals(html_text: str) -> tuple[bool, int, List[str]]:
    """Combine independent signals into a final paywall decision."""
    score_jsonld, reasons_jsonld = _jsonld_accessibility_signal(html_text)
    score_heuristic, reasons_heuristic = _heuristic_paywall_signal(html_text)

    score_total = score_jsonld + score_heuristic
    threshold = int(getattr(config, "PAYWALL_SCORE_THRESHOLD", 60))
    is_paywalled = score_total >= threshold

    reasons = reasons_jsonld + reasons_heuristic
    return is_paywalled, score_total, reasons


def _resolve_paywall_html_log_path() -> Optional[Path]:
    """Return configured HTML log path, or None if paywalled-entry logging is disabled."""
    configured_path = getattr(config, "PAYWALL_CLASSIFIED_ARTICLES_HTML_FILE", None)
    if configured_path is None:
        return None
    if isinstance(configured_path, Path):
        return configured_path
    if isinstance(configured_path, str):
        configured_path = configured_path.strip()
        if not configured_path:
            return None
        return Path(configured_path)
    return None


def _append_paywalled_entries_html(paywalled_entries: List) -> None:
    """Append paywalled article links as simplified HTML lines."""
    output_path = _resolve_paywall_html_log_path()
    if output_path is None:
        return

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        existing_urls: set[str] = set()
        if output_path.exists():
            existing_urls = set(re.findall(r'href="([^"]+)"', output_path.read_text(encoding="utf-8")))
        with open(output_path, mode="a", encoding="utf-8") as f:
            for entry in paywalled_entries:
                link_raw = getattr(entry, "link", "") or ""
                if not link_raw or link_raw in existing_urls:
                    continue
                existing_urls.add(link_raw)
                title_raw = getattr(entry, "title", "") or "[Ohne Titel]"
                link = escape(link_raw, quote=True)
                title = escape(title_raw)
                f.write(f'<a href="{link}">{title}</a><br>\n')
    except Exception as e:
        logger.warning("Failed to append paywalled entries HTML log: %s", e)


def compute_hex_checksum(input_string: str) -> str:
    """Computes a non-cryptographic, persistent CRC32 checksum of a string."""
    # Encode the string to bytes
    data_bytes = input_string.encode('utf-8')

    # Calculate the CRC32 checksum
    checksum = zlib.crc32(data_bytes)

    # Ensure a positive 32-bit integer result (0 to 4294967295)
    positive_checksum = checksum & 0xFFFFFFFF

    # convert to hex str with 8 digits
    checksum = hex(positive_checksum)[2:].zfill(8)
    
    return checksum


def _parse_multiple_date_formats(timestamp_str: str) -> Optional[datetime]:
    """Attempts to parse a timestamp string using a list of potential formats."""
    # The list of possible format strings for the given examples
    formats: List[str] = [
        # Format for: "Wed, 29 Oct 2025 13:40:19 +0100" (with %z for offset)
        "%a, %d %b %Y %H:%M:%S %z",
        # Format for: "Thu, 20 Feb 2025 10:00:00 GMT" (with %Z for name)
        "%a, %d %b %Y %H:%M:%S %Z",
        # Format for: "2025-10-28T19:30:00+00:00"
        "%Y-%m-%dT%H:%M:%S%z",
    ]

    for fmt in formats:
        try:
            # Attempt to parse the string with the current format
            dt_object = datetime.strptime(timestamp_str, fmt)
            # if dt_object is timezone-naive
            if dt_object.tzinfo is None:
                # Convert to UTC
                return pytz.utc.localize(dt_object)
            else:
                return dt_object
        except ValueError:
            # If parsing fails, try the next format
            continue

    # If no format matches after trying all, return None
    return None


def timediff_filter(n_hours: int, rss_entries: List) -> Dict:
    """
    Filter RSS entries based on their publication date being within the last n_hours.

    This function assumes that each entry has a 'published' or 'updated' attribute
    that can be parsed into a datetime object.

    Args:
        n_hours: Number of hours to look back from the current time.
        rss_entries: List of RSS entries to filter.

    Returns:
        List of RSS entries published within the last n_hours.
    """
    now = datetime.now(pytz.utc)
    filtered_entries = []

    for entry in rss_entries:
        pub_date_str = getattr(entry, 'published', '') or getattr(entry, 'updated', '')
        if pub_date_str:
            pub_date = _parse_multiple_date_formats(pub_date_str)
            if pub_date and (now - pub_date) <= timedelta(hours=n_hours):
                n_hours_ago = int((now - pub_date).total_seconds() / 3600)
                entry.hours_ago = n_hours_ago  # Store hours ago for later use
                entry.pub_date = pub_date  # Store parsed date for later use
                filtered_entries.append(entry)

    n_filtered_by_timediff = len(rss_entries) - len(filtered_entries)

    return {
        "filtered_entries": filtered_entries,
        "n_filtered_by_timediff": n_filtered_by_timediff
    }


def blacklist_filter(filtered_entries: Dict, blacklist_link: List[str], blacklist_title: List[str]) -> Dict:
    """
    Filter RSS entries based on blacklisted links and titles from config.

    This function is case-insensitive, tolerates missing `link`/`title` attributes
    on entries, and handles missing or empty blacklist lists in the config.

    Args:
        filtered_entries: Dict with filtered_entries list
        config: Configuration dict

    Returns:
        Dict with filtered entries
    """
    def entry_is_blacklisted(entry) -> bool:
        link = entry.link.lower()
        title = entry.title.lower()

        if blacklist_link and any(pattern in link for pattern in blacklist_link):
            return True
        if blacklist_title and any(pattern in title for pattern in blacklist_title):
            return True
        return False

    rss_entries = filtered_entries["filtered_entries"]
    filtered_entries["filtered_entries"] = [entry for entry in rss_entries if not entry_is_blacklisted(entry)]
    n_filtered_by_blacklist = len(rss_entries) - len(filtered_entries["filtered_entries"])
    filtered_entries["n_filtered_by_blacklist"] = n_filtered_by_blacklist

    return filtered_entries


async def is_behind_paywall(session: aiohttp.ClientSession, url: str) -> tuple[str, bool, list[str]]:
    """Check if URL is paywalled asynchronously."""
    timeout_s = int(getattr(config, "PAYWALL_REQUEST_TIMEOUT_SECONDS", 20))
    retries = int(getattr(config, "PAYWALL_REQUEST_RETRIES", 1))

    for attempt in range(retries + 1):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout_s)) as response:
                text = await response.text(errors="ignore")
                text_lower = text.lower()
                is_paywalled, score, reasons = _is_paywalled_by_signals(text_lower)

                logger.debug(
                    "paywall check url=%s status=%s score=%s result=%s reasons=%s",
                    url,
                    response.status,
                    score,
                    is_paywalled,
                    reasons[:5],
                )
                return (url, is_paywalled, reasons)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            if attempt < retries:
                await asyncio.sleep(0.25 * (attempt + 1))
                continue
            # On repeated network errors, include the entry (fail open).
            logger.warning("Paywall check failed after retries for url=%s error=%s", url, e)
            return (url, False, [])
        except Exception as e:
            # On non-network parsing/runtime errors, include the entry (fail open).
            logger.exception(f"{e}, url: {url}")
            return (url, False, [])

    return (url, False, [])


async def check_paywalls_async(rss_entries: List) -> dict:
    """Check all RSS entries for paywalls concurrently."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    async with aiohttp.ClientSession(headers=headers) as session:
        tasks = [is_behind_paywall(session, entry.link) for entry in rss_entries]
        results = await asyncio.gather(*tasks)
        return {url: (is_paywalled, reasons) for url, is_paywalled, reasons in results}


def paywall_filter(filtered_entries: Dict, feed: dict) -> Dict:
    """Filter RSS entries based on whether they are behind a paywall.
    
    This async version is 40-100x faster than the original for large lists.
    """
    if not feed.get("check_paywall", False):
        filtered_entries["n_filtered_by_paywall"] = 0
        return filtered_entries
    
    # Run async checks and get results
    rss_entries = filtered_entries["filtered_entries"]
    paywall_status = asyncio.run(check_paywalls_async(rss_entries))

    # Only log entries not detected via isaccessibleforfree (unreliable for logging purposes)
    entries_to_log = [
        entry for entry in rss_entries
        if paywall_status.get(entry.link, (False, []))[0]
        and "jsonld:isaccessibleforfree=false" not in paywall_status[entry.link][1]
    ]
    if entries_to_log:
        _append_paywalled_entries_html(entries_to_log)

    filtered_entries["filtered_entries"] = [
        entry for entry in rss_entries if not paywall_status.get(entry.link, (False, []))[0]
    ]

    n_filtered_by_paywall = len(rss_entries) - len(filtered_entries["filtered_entries"])
    filtered_entries["n_filtered_by_paywall"] = n_filtered_by_paywall

    return filtered_entries


def description_filter(filtered_entries: Dict, feed: dict) -> Dict:
    """Filter and clean up the descriptions of RSS entries based on the feed configuration."""
    rss_entries = filtered_entries["filtered_entries"]
    for entry in rss_entries:
        if hasattr(entry, 'description') and len(entry.description) < 1000:
            if "desc_filter" in feed:
                desc_filter_func = getattr(filter_module, f"desc_filter_{feed['desc_filter']}")
                entry.description = desc_filter_func(entry.description)
        else:
            entry.description = ""

    return filtered_entries


def highlight_filter(filtered_entries: Dict, highlight_title: List[str]) -> Dict:
    """Highlight RSS entries"""
    rss_entries = filtered_entries["filtered_entries"]

    if not highlight_title:
        return filtered_entries

    for entry in rss_entries:
        title = entry.title.lower()
        if any(pattern in title for pattern in highlight_title):
            entry.highlight = True

    return filtered_entries

def load_secrets() -> dict:
    """Load secrets from a JSON file."""
    secrets_file_fq = Path(__file__).parent.parent.parent / "secrets" /config.SECRETS_FILE
    try:
        with open(secrets_file_fq, "r", encoding="utf-8") as f:
            secrets = json.load(f)
            return secrets
    except Exception as e:
        logger.error(f"Error loading secrets file: {e}")
        return {}


def send_msg_gmail(
        subject: str,
        html_body: str,
        recipients: List[str],
        attachment_fname: str,
        attachment_html: str = None
    ) -> None:
    
    secrets = load_secrets()
    sender_email = secrets.get("sender_email")
    sender_password = secrets.get("sender_password")

    msg = MIMEMultipart()
    msg['Subject'] = subject
    msg['From'] = sender_email
    msg['To'] = ", ".join(recipients)

    msg.attach(MIMEText(html_body, 'html'))

    part = MIMEText(attachment_html, 'base64', 'utf-8')
    part.add_header('Content-Disposition', f'attachment; filename="{attachment_fname}"',)
    msg.attach(part)

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, recipients, msg.as_string())


def load_precomputed_render_data(uid: str) -> dict:
    """Load precomputed render data from file."""
    precomputed_file_fq = Path(__file__).parent.parent.parent / f"render_data_{uid}.json"
    try:
        with open(precomputed_file_fq, "r", encoding="utf-8") as f:
            import json
            render_data = json.load(f)
            logger.info(f"Loaded precomputed render data for user {uid}")
            return render_data
    except Exception as e:
        logger.error(f"Error loading precomputed render data for user {uid}: {e}")
    
    return {}