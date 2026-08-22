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
    ):
        self._uid = uid
        self.consumption_modes = set(consumption_modes)  # Consumption modes: e.g. {"web", "email"}
        self._recipients = recipients
        self._source_sort_order = source_sort_order
        self._blacklist_link = blacklist_link
        self._blacklist_title = blacklist_title
        self._highlight_keywords = highlight_keywords
        self._hours_back = hours_back
        self.render_data = {}

        # Load user feeds with optional source filtering and limit
        self._user_feeds_by_url = {}
        feed_count = 0
        for user_feed in user_feeds:
            if config.SOURCE_FILTER and user_feed["source"] not in config.SOURCE_FILTER:
                continue
            if feed_count >= limit:
                break
            self._user_feeds_by_url[user_feed["url"]] = user_feed
            feed_count += 1


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

    def clicktrack(self, lid: str, rating: int) -> bool:
        """Records the link click tracking information for a given link ID.

        This method tracks user interactions with links by saving link information to a JSONL file.
        The tracking data is stored in a user-specific file named 'clicktrack_[uid].jsonl'.

        Args:
            lid (str): The link ID to track.
            rating (int): Rating for the article.

        Returns:
            bool: True if tracking was successful, False if the link ID information could not be found.
        """
        lid_info = self.get_lid_info(lid)
        if lid_info is None:
            return False
        lid_info["rating"] = rating
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
        sort_order = self._source_sort_order
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

        user_feed_pool = self._user_feeds_by_url.keys()

        # Fetch and process feeds asynchronously
        output = process_feeds(user_feed_pool, uid=self._uid )
        successful_feeds_by_url = output['successful_by_url']

        # Process each feed's entries
        for feed in self._user_feeds_by_url.values():
            if feed['url'] not in successful_feeds_by_url:
                continue
            feed_raw_content = successful_feeds_by_url[feed['url']].raw_content
            feed_source = feed['source']
            feed_topic = feed.get('topic', 'Thema unbekannt')
            feed_info = f"{feed_source} - {feed_topic}"
            rss = feedparser.parse(feed_raw_content)
            feed_bozo_status = f" Bozo {repr(rss.bozo)} ({rss.bozo_exception})," if rss.bozo else ""

            if len(rss.entries) == 0:
                logger.debug(f"feed [{feed_info:39}]{feed_bozo_status} has no entries, skipping")
                continue

            # Apply filters
            filtered_entries = tools.timediff_filter(self._hours_back, rss.entries)
            filtered_entries = tools.blacklist_filter(filtered_entries, self._blacklist_link, self._blacklist_title)
            filtered_entries = tools.paywall_filter(filtered_entries, feed)
            filtered_entries = tools.description_filter(filtered_entries, feed)
            filtered_entries = tools.highlight_filter(filtered_entries, self._highlight_keywords)

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

            # Collect stories, avoiding duplicates by link ID and title
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
                        "hours_ago": entry.hours_ago,
                        "lid": entry_link_id,
                        "highlight": True if hasattr(entry, 'highlight') and entry.highlight else False,
                        "is_duplicate": False,
                        "duplicates": [],
                    }


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

        # Tag stories similar to previously clicked ("liked") entries using the ML model
        n_total_ml_tagged = 0
        if config.ML_TAG_ENABLED:
            ml_tagger = MLTagger(uid=self._uid, semantic_model=detector.semantic_model)
            n_total_ml_tagged = ml_tagger.tag_stories(self._stories_by_lid)

        # Group stories by source and topic (excluding duplicates from grouping)
        by_source = {}
        by_topic = {}
        for story in self._stories_by_lid.values():
            # Skip stories that are marked as duplicates
            if story.get('is_duplicate', False):
                continue
                
            if story['source'] not in by_source:
                by_source[story['source']] = []
            by_source[story['source']].append(story)

            if story['topic'] not in by_topic:
                by_topic[story['topic']] = []
            by_topic[story['topic']].append(story)

        # sort by_source by topic, number of duplicates (descending), and hours_ago
        for source in by_source:
            by_source[source].sort(key=lambda item: (item['topic'], -len(item.get('duplicates', [])), item['hours_ago']))
        
        # sort by_topic by number of duplicates (descending) and hours_ago
        for topic in by_topic:
            by_topic[topic].sort(key=lambda item: (-len(item.get('duplicates', [])), item['hours_ago']))

        self.render_data = {
            "by_source": by_source,
            "by_topic": by_topic,
            "by_lid": self._stories_by_lid,
            "new_entries": n_new_entries,
            "n_highlighted": n_total_highlighted,
            "n_ml_tagged": n_total_ml_tagged,
            "n_filtered": n_total_filtered_by_blacklist,
            "date": datetime.now(pytz.timezone('Europe/Berlin')).strftime("%d.%m.%Y %H:%M"),
            "hours_back": self._hours_back,
            "uid": self._uid,
        }

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
            recipients=self._recipients,
            attachment_html=render_app(self.render_data),
            attachment_fname="feeds.html"
        )


class NewsFeedManager:
    def __init__(
            self,
            user_cfgs: List[Dict[str, any]],
            hours_back: int = 24,
            limit: int = 999
    ):
        
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
            )

    def get_news_feed_user(self, uid: str) -> NewsFeedUser:
        return self.news_feed_users_by_uid.get(uid)

