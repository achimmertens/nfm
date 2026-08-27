import logging
import feedparser
from datetime import datetime
from typing import List, Dict, Set  # noqa: F401
from pathlib import Path
import json
import pytz

import app.core.tools as tools
import app.conf.config as config

from app.core.feedprocessor import process_feeds
from app.core.dedup import StoryDuplicateDetector
from app.core.ml import MLTagger, maybe_retrain
from app.core.render import render_app

logger = logging.getLogger(__name__)

class NewsFeedUser:
    # Shared across instances (survives config-reload manager rebuilds):
    # uid -> last fully rendered story pool (duplicates + ML). Incremental
    # previews read this so "similar articles" stay visible while a fresh
    # render cycle is still analysing, even when /reload rebuilt the manager.
    _last_complete_by_uid: Dict[str, Dict] = {}

    def __init__(
            self,
            uid: str,
            consumption_modes: List[str],
            recipients: List[str],
            source_sort_order: Dict[str, int],
            blacklist_link: List[str],
            blacklist_title: List[str],
            highlight_keywords: List[str],
            user_feeds: List[Dict[str, any]],
            hours_back: int = 24,
            limit: int = 999,
            settings_store=None,
    ):
        self._uid = uid
        self.consumption_modes = set(consumption_modes)  # Consumption modes: e.g. {"web", "email"}
        self._recipients = recipients
        self._source_sort_order = source_sort_order
        self._blacklist_link = blacklist_link
        self._blacklist_title = blacklist_title
        self._highlight_keywords = highlight_keywords
        self._hours_back = hours_back
        self.render_data = {
            # Empty-but-valid placeholder so the template can render during the
            # window between cold start and the first published preview (the
            # initial render runs in the background). Without this, GET /{uid}
            # raises jinja2 UndefinedError: 'dict object' has no attribute
            # 'by_source' for the first seconds after a restart.
            "by_source": {},
            "by_topic": {},
            "by_breaking": {},
            "by_lid": {},
            "source_descriptions": {},
            "new_entries": 0,
            "n_highlighted": 0,
            "n_ml_tagged": 0,
            "n_filtered": 0,
            "date": datetime.now(pytz.timezone('Europe/Berlin')).strftime("%d.%m.%Y %H:%M"),
            "hours_back": hours_back,
            "uid": uid,
        }
        # Last fully rendered story pool (after duplicate detection + ML).
        # Kept across render cycles so the incremental preview can keep showing
        # the last known duplicate sets while the JSON run is still analysing.
        self._last_complete_by_lid = self._last_complete_by_uid.get(self._uid)
        # Progress of the current render (used by the frontend banner while the
        # feeds are being analysed after a cold start / reload).
        self.render_status = {
            "status": "idle",
            "phase": "",
            "percent": 0,
            "current_source": "",
            "current_topic": "",
            "done_feeds": 0,
            "total_feeds": 0,
            "message": "",
            "uid": uid,
        }
        # Optional runtime settings store. When set, filter/feed values are
        # read live from the store on every render cycle, so GUI changes take
        # effect on the next update (or forced refresh) without a restart.
        self._settings_store = settings_store

        # Load user feeds with optional source filtering and limit
        self._user_feeds_by_url = self._apply_feed_selection(user_feeds, limit)

    # ------------------------------------------------------------------
    # Runtime (settings-store aware) accessors
    # ------------------------------------------------------------------
    def _store(self):
        """Return the runtime settings store, or None if not configured."""
        return getattr(self, "_settings_store", None)

    def _apply_feed_selection(self, feeds, limit=None) -> Dict[str, dict]:
        """Build the {url: feed} pool, honoring SOURCE_FILTER and feed LIMIT."""
        if limit is None:
            limit = int(getattr(config, "LIMIT", 999))
        source_filter = getattr(config, "SOURCE_FILTER", []) or []
        by_url = {}
        count = 0
        for user_feed in feeds:
            if source_filter and user_feed["source"] not in source_filter:
                continue
            if count >= limit:
                break
            by_url[user_feed["url"]] = user_feed
            count += 1
        return by_url

    def _current_feeds_by_url(self) -> Dict[str, dict]:
        """Feeds currently effective for this user (live from settings store)."""
        store = self._store()
        if store is not None:
            feeds = self._settings_store.get_user_feeds(self._uid)
            if feeds is not None:
                return self._apply_feed_selection(feeds)
        return dict(self._user_feeds_by_url)

    def _source_descriptions(self) -> Dict[str, str]:
        """Map of source name -> description.

        Looked up from the runtime feed pool first, falling back to the
        config.py defaults, so descriptions are available even when the
        runtime overlay carries a feed list without them.
        """
        descriptions: Dict[str, str] = {}
        # 1) config.py defaults
        for ucfg in getattr(config, "user_cfgs", []) or []:
            if (ucfg.get("settings") or {}).get("uid") != self._uid:
                continue
            for feed in ucfg.get("feeds", []) or []:
                desc = feed.get("description")
                if desc:
                    descriptions.setdefault(feed.get("source"), desc)
        # 2) runtime feed pool (may add/override)
        for feed in self._current_feeds_by_url().values():
            desc = feed.get("description")
            if desc:
                descriptions.setdefault(feed["source"], desc)
        return descriptions

    _BREAKING_TOPIC = "Eilmeldungen"

    def _is_breaking_news(self, story, feed_topic: str) -> bool:
        """Decide whether a story qualifies as a breaking-news ("Eilmeldung")
        article according to the source-specific rules requested by the user.

        Rules (case-insensitive title matching):
          * Spiegel : "eilmeldung" in title  OR  comes from the dedicated
                      Eilmeldungen feed (``feed_topic == "Eilmeldungen"``).
          * Tagesschau : "+++" in title. (+++ is the central breaking marker;
                      the very-short-age rule is intentionally NOT enforced here
                      because JEDE Tagesschau-Kurzmeldung nutzt +++ – ein
                      zusätzlicher Altersfilter würde echte +++-Titel fälschlich
                      ausblenden, wenn sie einige Minuten alt sind. Die
                      Erkennung über +++ allein ist zuverlässiger/erklärbarer.)
          * Heise : "update" in title  AND  published < 30 minutes ago.
          * Golem : "eilmeldung" OR "breaking" in title.
          * n-tv  : title starts with "breaking" (prefix).
          * DW    : "eilmeldung" in title.
        Sources without a rule (T-online, Stern, Focus …) return False.

        NOTE on the ``hours_ago`` unit (verified in app/core/tools.py
        ``timediff_filter``): ``entry.hours_ago = int(...)`` — it is an INTEGER
        number of full hours (0 for anything < 1h). It therefore CANNOT express
        "< 30 minutes". For the Heise rule we use the exact UTC epoch stored on
        the story as ``pub_ts`` (a UTC timestamp added at ingest). NB: the
        human-readable ``pub_date`` string holds the feed's WALL-CLOCK time (its
        timezone offset was dropped by strftime), so it must NOT be re-localised
        as UTC for age math — that would misinterpret local times as UTC and
        produce wrong (often negative) ages. ``pub_ts`` avoids that entirely.
        """
        title = (story.get("title") or "").lower()
        source = story.get("source") or ""
        if source == "Spiegel":
            if feed_topic == "Eilmeldungen":
                return True
            return "eilmeldung" in title
        if source == "Tagesschau":
            return "+++" in title
        if source == "Heise":
            if "update" not in title:
                return False
            # Exact <30 min check via the UTC epoch timestamp stored at ingest.
            ts = story.get("pub_ts")
            if ts is None:
                # Fallback without precise age: do NOT guess <30 min.
                return False
            return (datetime.now(pytz.utc).timestamp() - ts) < 1800
        if source == "Golem":
            return "eilmeldung" in title or "breaking" in title
        if source == "n-tv":
            return title.startswith("breaking")
        if source == "DW":
            return "eilmeldung" in title
        return False

    def _group_render_data(self, stories_by_lid: Dict):
        """Build the by_source / by_topic / by_breaking grouping from a story pool.

        Duplicate stories are excluded from the grouping. Breaking-news
        ("Eilmeldungen") articles are grouped BOTH under their real topic AND
        under an additional ``by_topic["Eilmeldungen"]`` bucket (backward
        compatible), AND collected in a dedicated standalone ``by_breaking``
        bucket so the frontend can render a separate "Eilmeldungen" section.
        The real ``topic`` field of every story stays untouched (extra grouping
        only).
        """
        by_source = {}
        by_topic = {}
        by_breaking = {}
        for story in stories_by_lid.values():
            if story.get("is_duplicate", False):
                continue
            by_source.setdefault(story["source"], []).append(story)
            by_topic.setdefault(story["topic"], []).append(story)
            # Breaking-news detection (used both for the legacy
            # by_topic["Eilmeldungen"] bucket AND the dedicated by_breaking
            # section below).
            if self._is_breaking_news(story, story["topic"]):
                # Dedicated standalone breaking-news bucket.
                by_breaking.setdefault(self._BREAKING_TOPIC, []).append(story)
                # Legacy by_topic["Eilmeldungen"] bucket (in addition, never in
                # place of the topic). Guard: if the story's real topic already
                # IS "Eilmeldungen" (e.g. Spiegel-Eilmeldungen-Feed), it is
                # already in that bucket via the normal assignment – adding it
                # again would double it.
                if story["topic"] != self._BREAKING_TOPIC:
                    by_topic.setdefault(self._BREAKING_TOPIC, []).append(story)
        for source in by_source:
            by_source[source].sort(key=lambda item: (
                item["topic"], -len(item.get("duplicates", [])), item["hours_ago"]))
        for topic in by_topic:
            by_topic[topic].sort(key=lambda item: (
                -len(item.get("duplicates", [])), item["hours_ago"]))
        # Ensure "Eilmeldungen" sorts first (by_topic is insertion-ordered).
        if self._BREAKING_TOPIC in by_topic:
            by_topic = {self._BREAKING_TOPIC: by_topic[self._BREAKING_TOPIC],
                        **{k: v for k, v in by_topic.items()
                           if k != self._BREAKING_TOPIC}}
        # Sort the dedicated breaking-news bucket too.
        if self._BREAKING_TOPIC in by_breaking:
            by_breaking[self._BREAKING_TOPIC].sort(key=lambda item: (
                -len(item.get("duplicates", [])), item["hours_ago"]))
        return by_source, by_topic, by_breaking

    def _preview_merged_stories(self):
        """Build the by_lid story pool shown during a running render.

        Duplicate detection (and ML tagging) only run AFTER all feeds are
        fetched, so intermediate previews would otherwise expose every story
        with an empty ``duplicates`` list and the "similar articles" blocks
        vanish for minutes. To fix this we reuse the last fully rendered pool
        (``_last_complete_by_lid``): for each fresh story we copy over its last
        known duplicate set, matched by ``link``.

        Safety: a duplicate set is only copied when every referenced LID still
        exists in the fresh preview pool so the Jinja ``data['by_lid'][lid]``
        lookup can never raise a KeyError. A story is only flagged as a
        duplicate when it is actually referenced by a retained head in this
        preview, otherwise it stays visible on its own.

        ``_stories_by_lid`` itself is left untouched (we write to copies) so
        the real duplicate detection in ``update_render_data`` still operates
        on pristine data.
        """
        pool = self._stories_by_lid
        last_good = self._last_complete_by_lid
        if not last_good:
            # No previous finished render yet: expose the fresh pool as-is.
            return pool
        last_by_link = {
            s.get("link"): s for s in last_good.values() if s.get("link")
        }
        merged = {}
        referenced = set()  # lids that some retained head points to
        for lid, story in pool.items():
            m = dict(story)
            dup_lids = list(story.get("duplicates") or [])
            if not dup_lids:
                prev = last_by_link.get(story.get("link"))
                if prev:
                    dup_lids = [x for x in (prev.get("duplicates") or [])
                                if x in pool]
            m["duplicates"] = dup_lids
            m["is_duplicate"] = False
            for r in dup_lids:
                referenced.add(r)
            merged[lid] = m
        # Only tag as duplicate those that a retained head actually points to.
        for lid, m in merged.items():
            if lid in referenced:
                m["is_duplicate"] = True
        return merged

    def _publish_preview(self, message: str = ""):
        """Expose an up-to-date partial render while the full analysis runs.

        Called after every fully processed feed so the page shows whatever has
        already been read & grouped, and reports the current progress.
        """
        preview_pool = self._preview_merged_stories()
        by_source, by_topic, by_breaking = self._group_render_data(preview_pool)
        self.render_data = {
            "by_source": by_source,
            "by_topic": by_topic,
            "by_breaking": by_breaking,
            "by_lid": preview_pool,
            "source_descriptions": self._source_descriptions(),
            "new_entries": len(self._stories_by_lid),
            "n_highlighted": 0,
            "n_ml_tagged": 0,
            "n_filtered": 0,
            "date": datetime.now(pytz.timezone('Europe/Berlin')).strftime("%d.%m.%Y %H:%M"),
            "hours_back": self._current_hours_back(),
            "uid": self._uid,
            "render_status": self.render_status,
        }
        pct = int(self.render_status.get("done_feeds", 0) / max(1, self.render_status.get("total_feeds", 1)) * 100)
        self.render_status.update({
            "status": "running",
            "phase": "feeds",
            "percent": min(pct, 100),
            "message": message,
            "uid": self._uid,
        })

    def _finish_status(self):
        """Mark the render as finished."""
        self.render_status.update({
            "status": "done",
            "percent": 100,
            "phase": "done",
            "message": "Fertig",
            "done_feeds": self.render_status.get("total_feeds", 0),
            "uid": self._uid,
        })

    def _current_setting(self, name, fallback):
        """Read a per-user setting live from the settings store."""
        store = self._store()
        if store is not None:
            settings = self._settings_store.get_user_settings(self._uid)
            if settings is not None and name in settings:
                return settings[name]
        return fallback

    def _current_blacklist_link(self):
        return self._current_setting("blacklist_link", self._blacklist_link)

    def _current_blacklist_title(self):
        return self._current_setting("blacklist_title", self._blacklist_title)

    def _current_highlight_keywords(self):
        return self._current_setting("highlight_keywords", self._highlight_keywords)

    def _current_source_sort_order(self):
        return self._current_setting("source_sort_order", self._source_sort_order)

    def _current_recipients(self):
        return self._current_setting("recipients", self._recipients)

    def _current_hours_back(self):
        return int(getattr(config, "HOURS_BACK", self._hours_back))

    def get_lid_info(self, lid: str) -> dict:
        """Get link information by link ID."""
        if lid in self._stories_by_lid:
            return {
                "ts": datetime.now(pytz.utc).strftime("%d.%m.%y %H:%M:%S"),
                "lid": lid,
                "uid": self._uid,
                "source": self._stories_by_lid[lid]["source"],
                "topic": self._stories_by_lid[lid]["topic"],
                "title": self._stories_by_lid[lid]["title"],
                "description": self._stories_by_lid[lid]["description"],
                "link": self._stories_by_lid[lid]["link"],
            }
        else:
            return None

    def clicktrack(self, lid: str, rating: int, stars: int = 3) -> bool:
        """Records the link click tracking information for a given link ID.

        This method tracks user interactions with links by saving link information to a JSONL file.
        The tracking data is stored in a user-specific file named 'clicktrack_[uid].jsonl'.

        Args:
            lid (str): The link ID to track.
            rating (int): Rating for the article (0 = uninteressant, 1 = gesehen/positiv).
            stars (int, optional): Star rating 0-5 assigned by the user (default 3). A click
                (rating==1) automatically grants 3 stars, matching the "angesehen" default. The
                star value is used as the ML signal weight (more stars = stronger positive).

        Returns:
            bool: True if tracking was successful, False if the link ID information could not be found.
        """
        lid_info = self.get_lid_info(lid)
        if lid_info is None:
            return False
        lid_info["rating"] = rating
        lid_info["stars"] = max(0, min(int(stars), 5))
        uid = self._uid
        clicktrack_file_fq = Path(__file__).parent.parent.parent / "clicktrack" / f"clicktrack_{uid}.jsonl"
        with open(clicktrack_file_fq, "a", encoding="utf-8") as f:
            f.write(json.dumps(lid_info) + "\n")
        return True

    def save_negative_samples(self, lids: List[str], section_name: str, section_type: str) -> int:
        """Saves negative samples (unread items) for ML training.

        Records news items as negative training samples by writing them to the clicktrack file
        with rating=0. This data helps ML recommendation systems learn which content users are
        not interested in.

        Args:
            lids (List[str]): List of link IDs to record as negative samples.
            section_name (str): Name of the section (e.g., source or topic name).
            section_type (str): Type of section ('source' or 'topic').

        Returns:
            int: Number of negative samples successfully saved.
        """
        count = 0
        uid = self._uid
        clicktrack_file_fq = Path(__file__).parent.parent.parent / "clicktrack" / f"clicktrack_{uid}.jsonl"
        
        with open(clicktrack_file_fq, "a", encoding="utf-8") as f:
            for lid in lids:
                lid_info = self.get_lid_info(lid)
                if lid_info is not None:
                    lid_info["rating"] = 0
                   # lid_info["section_name"] = section_name
                   # lid_info["section_type"] = section_type
                    f.write(json.dumps(lid_info) + "\n")
                    count += 1
        
        return count

    def get_uninteresting_lids(self) -> set:
        """Returns the set of link IDs that the user has tagged as uninteresting (rating=0).

        Reads the clicktrack file and applies last-rating-wins logic per lid, so a lid
        that was later clicked (rating=1) is not treated as uninteresting.

        Returns:
            set: Set of lid strings with a final rating of 0.
        """
        latest_ratings: dict = {}
        uid = self._uid
        clicktrack_file_fq = Path(__file__).parent.parent.parent / "clicktrack" / f"clicktrack_{uid}.jsonl"
        if not clicktrack_file_fq.exists():
            return set()
        with open(clicktrack_file_fq, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    lid = record.get("lid")
                    rating = int(record.get("rating", 1))
                    if lid:
                        latest_ratings[lid] = rating  # last write wins
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue
        return {lid for lid, rating in latest_ratings.items() if rating == 0}


    def source_sort_func(self, lid: str) -> int:
        """Sortierfunktion für Quellen basierend auf der Konfiguration."""
        source = self._stories_by_lid[lid]['source']
        sort_order = self._current_source_sort_order()
        return sort_order.get(source, 9999)  # Standardwert für unbekannte Quellen

    def save_render_data_as_json(self, file_fq: Path) -> None:
        """Save the render data as a JSON file."""
        if self.render_data is None:
            self.update_render_data()
        with open(file_fq, mode="w", encoding="utf-8") as f:
            json.dump(self.render_data, f, ensure_ascii=False, indent=4)


    def update_render_data(self) -> None:
        """Render the news feeds based on the configuration."""
        logger.info(f"Updating render data for user {self._uid}")

        if config.USE_PRECOMPUTED_RENDER_DATA:
            logger.info("Using precomputed data, skipping feed processing")
            self.render_data = tools.load_precomputed_render_data(self._uid)
            return

        self._stories_by_lid = {}

        n_new_entries = 0
        n_total_filtered_by_timediff = 0
        n_total_filtered_by_blacklist = 0
        n_total_filtered_by_paywall = 0

        # Read the current (possibly runtime-edited) feed pool for this cycle
        feeds_by_url = self._current_feeds_by_url()
        user_feed_pool = feeds_by_url.keys()

        # Report progress for the frontend banner (cold start / reload guard)
        self.render_status.update({
            "status": "running",
            "phase": "fetch",
            "percent": 5,
            "done_feeds": 0,
            "total_feeds": len(feeds_by_url),
            "current_source": "",
            "current_topic": "",
            "message": "Feeds werden abgerufen…",
            "uid": self._uid,
        })

        # Fetch and process feeds asynchronously
        output = process_feeds(user_feed_pool, uid=self._uid )
        successful_feeds_by_url = output['successful_by_url']

        # Process each feed's entries
        processed = 0
        for feed in feeds_by_url.values():
            feed_source = feed['source']
            feed_topic = feed.get('topic', 'Thema unbekannt')
            processed += 1
            self.render_status.update({
                "phase": "feeds",
                "done_feeds": processed,
                "current_source": feed_source,
                "current_topic": feed_topic,
                "message": f"{feed_source} – {feed_topic}",
            })
            if feed['url'] not in successful_feeds_by_url:
                # No content for this feed, but still expose progress
                self._publish_preview()
                continue
            feed_info = f"{feed_source} - {feed_topic}"
            feed_raw_content = successful_feeds_by_url[feed['url']].raw_content
            rss = feedparser.parse(feed_raw_content)
            feed_bozo_status = f" Bozo {repr(rss.bozo)} ({rss.bozo_exception})," if rss.bozo else ""

            if len(rss.entries) == 0:
                logger.debug(f"feed [{feed_info:39}]{feed_bozo_status} has no entries, skipping")
                continue

            # Apply filters
            filtered_entries = tools.timediff_filter(self._current_hours_back(), rss.entries)
            filtered_entries = tools.blacklist_filter(filtered_entries, self._current_blacklist_link(), self._current_blacklist_title())
            filtered_entries = tools.paywall_filter(filtered_entries, feed)
            filtered_entries = tools.description_filter(filtered_entries, feed)
            filtered_entries = tools.highlight_filter(filtered_entries, self._current_highlight_keywords())

            # Accumulate filter statistics
            n_total_filtered_by_timediff += filtered_entries.get('n_filtered_by_timediff', 0)
            n_total_filtered_by_blacklist += filtered_entries.get('n_filtered_by_blacklist', 0)
            n_total_filtered_by_paywall += filtered_entries.get('n_filtered_by_paywall', 0)

            entries = filtered_entries["filtered_entries"]
            n_new_entries += len(entries)

            if len(entries) == 0:
                logger.debug(f"processing feed [{feed_info:39}]{feed_bozo_status} with {len(rss.entries)} entries but no new entries, skipping")
                continue
            else:
                logger.debug(f"processing feed [{feed_info:39}]{feed_bozo_status} with {len(rss.entries)} entries and {len(entries)} new entries")
            known_titles = []
            for entry in entries:
                entry_link_id = tools.compute_hex_checksum(entry.link)
                if entry_link_id in self._stories_by_lid or entry.title in known_titles:
                    logger.debug(f"   duplicate link found: {entry.link}")
                else:
                    known_titles.append(entry.title)
                    self._stories_by_lid[entry_link_id] = {
                        "source": feed_source,
                        "topic": feed_topic,
                        "title": entry.title if entry.title else "[Ohne Titel]",
                        "link": entry.link,
                        "description": entry.description,
                        "pub_date": entry.pub_date.strftime("%d.%m.%Y %H:%M:%S"),
                        "pub_ts": entry.pub_date.timestamp(),  # UTC epoch, exakte Freshness für Eilmeldungen
                        "hours_ago": entry.hours_ago,
                        "lid": entry_link_id,
                        "highlight": True if hasattr(entry, 'highlight') and entry.highlight else False,
                        "is_duplicate": False,
                        "duplicates": [],
                    }

            # Expose an up-to-date partial render after each processed feed
            self._publish_preview()

        # Duplikaterkennung initialisieren
        detector = StoryDuplicateDetector(
            tfidf_threshold=0.25,
            semantic_threshold=0.70,
            use_semantic=True,
            uid=self._uid
        )

        # Duplikate finden und kennzeichnen
        duplicates = detector.find_all_duplicates(self._stories_by_lid)
        clusters = detector.get_duplicate_clusters(duplicates)

        # Verarbeite die gefundenen Duplikat-Cluster
        for cluster in clusters:
            # Wähle den "Haupt"-LID basierend auf einer Sortierfunktion aus
            sorted_cluster = sorted(cluster, key=self.source_sort_func)
            lid_head = sorted_cluster[0]
            # Weise die restlichen LIDs als Duplikate zu
            self._stories_by_lid[lid_head]["duplicates"] = sorted_cluster[1:]
            # Markiere die Duplikate
            for lid in self._stories_by_lid[lid_head]["duplicates"]:
                self._stories_by_lid[lid]['is_duplicate'] = True    

        # Füge Stern-Symbole zu hervorgehobenen Geschichten hinzu und zähle sie
        n_total_highlighted = 0
        for story in self._stories_by_lid.values():
            if story['highlight'] and not story['is_duplicate']:
                n_total_highlighted += 1
                story['title'] = f"⭐ {story['title']}"

        # Tag stories similar to previously clicked ("liked") entries using ML
        n_total_ml_tagged = 0
        if config.ML_TAG_ENABLED:
            ml_tagger = MLTagger(uid=self._uid, semantic_model=detector.semantic_model)
            n_total_ml_tagged = ml_tagger.tag_stories(self._stories_by_lid)
            # ML tagging can take a while; expose a fresh preview (deduped)
            self._publish_preview()

        # Group stories by source and topic (excluding duplicates from grouping)
        by_source, by_topic, by_breaking = self._group_render_data(self._stories_by_lid)

        self.render_data = {
            "by_source": by_source,
            "by_topic": by_topic,
            "by_breaking": by_breaking,
            "by_lid": self._stories_by_lid,
            "source_descriptions": self._source_descriptions(),
            "new_entries": n_new_entries,
            "n_highlighted": n_total_highlighted,
            "n_ml_tagged": n_total_ml_tagged,
            "n_filtered": n_total_filtered_by_blacklist,
            "date": datetime.now(pytz.timezone('Europe/Berlin')).strftime("%d.%m.%Y %H:%M"),
            "hours_back": self._current_hours_back(),
            "uid": self._uid,
            "render_status": self.render_status,
        }
        # Remember this fully rendered (deduplicated + ML-tagged) pool so the
        # next render cycle can keep showing these duplicate sets during its
        # incremental previews, instead of briefly exposing empty lists.
        self._last_complete_by_lid = {
            lid: dict(story) for lid, story in self._stories_by_lid.items()
        }
        type(self)._last_complete_by_uid[self._uid] = self._last_complete_by_lid
        self._finish_status()

        # Retrain the ML model if the clicktrack file has grown large enough (checked hourly)
        if config.ML_TAG_ENABLED:
            try:
                maybe_retrain(self._uid, semantic_model=detector.semantic_model)
            except Exception:
                logger.exception(f"[{self._uid}] ML retrain check failed")


    def send_app_via_email(self) -> None:
        """Send the rendered feeds via email."""

        if not self.render_data or 'web' not in self.consumption_modes:
            self.update_render_data()
        
        tools.send_msg_gmail(
            subject="Newsreader Update",
            html_body="""
                    <body style="font-family:Arial, sans-serif; background:#1e1e1e; color:#ccc; padding:20px;">
                    <h2 style="color:#fff;">Aktuelle Nachrichten</h2>
                    <p>Die neuesten Schlagzeilen befinden sich in der beigefügten HTML-Datei:</p>
                    </body>
                    """,
            recipients=self._current_recipients(),
            attachment_html=render_app(self.render_data),
            attachment_fname="feeds.html"
        )


class NewsFeedManager:
    def __init__(
            self,
            user_cfgs: List[Dict[str, any]],
            hours_back: int = 24,
            limit: int = 999,
            settings_store=None,
    ):

        self._settings_store = settings_store
        self.news_feed_users_by_uid = {}       

        for user_cfg in user_cfgs:
            uid = user_cfg["settings"]["uid"]
            logger.info(f"[{uid}] reading configuration")
            self.news_feed_users_by_uid[uid] = NewsFeedUser(
                uid=uid,
                consumption_modes=user_cfg["settings"]["consumption_modes"],
                recipients=user_cfg["settings"]["recipients"],
                source_sort_order=user_cfg["settings"]["source_sort_order"],
                blacklist_link=user_cfg["settings"]["blacklist_link"],
                blacklist_title=user_cfg["settings"]["blacklist_title"],
                highlight_keywords=user_cfg["settings"]["highlight_keywords"],
                user_feeds=user_cfg["feeds"],
                hours_back=hours_back,
                limit=limit,
                settings_store=self._settings_store,
            )

    def get_news_feed_user(self, uid: str) -> NewsFeedUser:
        return self.news_feed_users_by_uid.get(uid)
