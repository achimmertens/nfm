"""Runtime settings store for NFM.

This module provides a small, database-free persistence layer that lets per-user
and global News Feed settings be edited at runtime (via the web settings GUI)
and take effect immediately, without a restart.

Mechanism
---------
1.  The canonical *defaults* live in :mod:`app.conf.config`:
    - per-user defaults come from ``config.user_cfgs`` (each entry is a dict with
      ``settings`` and ``feeds``),
    - global defaults are plain module constants (``LIMIT``, ``HOURS_BACK``,
      ``SOURCE_FILTER``, ``CRONTRIGGER``, ``ENABLE_HIDE_UNREAD``,
      ``DEPLOY_MANIFEST``, the paywall thresholds and the ML settings).

2.  A single JSON file (``runtime-settings.json`` by default, configurable via
    ``config.RUNTIME_SETTINGS_FILE`` or the ``NFM_RUNTIME_SETTINGS`` env var)
    holds a *merge overlay*:

        {
          "global": { "<GLOBAL_KEY>": value, ... },      // optional overrides
          "users": {
            "<uid>": { "settings": {...}, "feeds": [...] }   // optional overrides
          }
        }

    On startup the app first builds the effective configuration from the
    ``config.py`` defaults, then overlays them with this file (field-by-field
    for the per-user settings, and per-key for the global block). The result is
    the "effective" configuration that the rest of the app reads.

3.  When the GUI saves changed settings via ``PUT /{uid}/settings``, the store
    merges the new values into the effective configuration, applies the global
    block immediately by writing the values back onto the live ``config`` module
    (so modules that read ``config.XXX`` — e.g. the ML tagger or the paywall
    detector — pick them up on their next run), and persists the overlay to the
    JSON file with an atomic write.

Containers
----------
For docker/container deployments the JSON file path defaults to *CWD-relative*,
so a container's working directory naturally becomes the location. To persist
across container restarts, the orchestrator should either set ``CWD`` to (or
bind-mount a persistent directory onto) a writable path and set
``NFM_RUNTIME_SETTINGS`` to a file inside that mount, e.g.::

    NFM_RUNTIME_SETTINGS=/data/nfm/runtime-settings.json

If a bind-mounted directory is not writable at app start the store still
resolves the effective configuration in-memory from ``config.py``; persistence
writes will fail gracefully (logged, not fatal).
"""

from __future__ import annotations

import json
import logging
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional

import app.conf.config as config

logger = logging.getLogger(__name__)

# Global settings keys that are exposed/editable at runtime. Each key is also
# an attribute on the `config` module (same spelling), which is what the rest
# of the app reads at call time.
GLOBAL_KEYS: List[str] = [
    "LIMIT",
    "HOURS_BACK",
    "SOURCE_FILTER",
    "CRONTRIGGER",
    "ENABLE_HIDE_UNREAD",
    "DEPLOY_MANIFEST",
    "PAYWALL_SCORE_THRESHOLD",
    "PAYWALL_REQUEST_TIMEOUT_SECONDS",
    "PAYWALL_REQUEST_RETRIES",
    "ML_TAG_ENABLED",
    "ML_TAG_THRESHOLD",
    "ML_RETRAIN_THRESHOLD_BYTES",
    "ML_NEGATIVE_WEIGHT",
    "ML_NEGATIVE_CAP_MULTIPLIER",
]

# Per-user setting keys that belong under "settings" (feeds are separate).
USER_SETTING_KEYS: List[str] = [
    "uid",
    "consumption_modes",
    "recipients",
    "source_sort_order",
    "blacklist_link",
    "blacklist_title",
    "highlight_keywords",
]

_RUNTIME_FILE_VERSION = 1


def _resolve_runtime_path() -> Path:
    """Resolve the runtime settings file path.

    Priority:
      1. ``NFM_RUNTIME_SETTINGS`` environment variable (container-friendly).
      2. ``config.RUNTIME_SETTINGS_FILE`` (falls back to 'runtime-settings.json'),
         resolved relative to the process CWD.
    """
    env_path = os.environ.get("NFM_RUNTIME_SETTINGS")
    if env_path:
        return Path(env_path)
    fname = getattr(config, "RUNTIME_SETTINGS_FILE", "runtime-settings.json")
    return Path(fname)


class SettingsStore:
    """Loads/merges/persists runtime settings on top of the config defaults."""

    def __init__(
        self,
        runtime_file: Optional[Path] = None,
        user_cfgs: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self._runtime_file = Path(runtime_file) if runtime_file else _resolve_runtime_path()
        self._user_cfgs = user_cfgs if user_cfgs is not None else getattr(config, "user_cfgs", [])
        # Effective (merged) state. Filled by load().
        self._user_by_uid: Dict[str, Dict[str, Any]] = {}
        self._global: Dict[str, Any] = {}
        self.load()

    # ------------------------------------------------------------------ load

    def load(self) -> None:
        """(Re)build the effective config from config.py defaults + runtime file."""
        self._user_by_uid = self._default_user_dicts()
        self._global = self._default_global()

        file_data: Dict[str, Any] = {}
        if self._runtime_file.exists():
            try:
                file_data = json.loads(self._runtime_file.read_text(encoding="utf-8"))
            except Exception:
                logger.exception(
                    "Failed to parse runtime settings file %s; using config.py defaults",
                    self._runtime_file,
                )
                file_data = {}

        # Overlay the global block.
        file_global = file_data.get("global") if isinstance(file_data, dict) else None
        if isinstance(file_global, dict):
            for key in GLOBAL_KEYS:
                if key in file_global:
                    self._global[key] = deepcopy(file_global[key])

        # Overlay the per-user blocks.
        file_users = file_data.get("users", {}) if isinstance(file_data, dict) else {}
        if isinstance(file_users, dict):
            for uid, block in file_users.items():
                if not isinstance(block, dict):
                    continue
                if uid not in self._user_by_uid:
                    # Runtime-only user (not in config.py). Keep its values, but
                    # note that no NewsFeedUser is instantiated for it unless the
                    # orchestrator adds it to config.py defaults too.
                    self._user_by_uid[uid] = deepcopy(block)
                    continue
                if isinstance(block.get("settings"), dict):
                    for key, value in block["settings"].items():
                        if key in USER_SETTING_KEYS:
                            self._user_by_uid[uid]["settings"][key] = deepcopy(value)
                if isinstance(block.get("feeds"), list):
                    self._user_by_uid[uid]["feeds"] = deepcopy(block["feeds"])

        # Push the effective globals onto the live config module so the rest of
        # the app (tools.py, ml.py, feedmgr.py) reads the runtime values.
        self.apply_global_to_config()
        logger.info(
            "SettingsStore: runtime file=%s users=%s (global overrides=%d)",
            self._runtime_file,
            ", ".join(sorted(self._user_by_uid)) or "-",
            sum(1 for k in GLOBAL_KEYS if k in file_global) if isinstance(file_global, dict) else 0,
        )

    # ------------------------------------------------------------ defaults

    def _default_user_dicts(self) -> Dict[str, Dict[str, Any]]:
        """Build effective default user dicts from config.user_cfgs."""
        result: Dict[str, Dict[str, Any]] = {}
        for cfg in self._user_cfgs or []:
            if not isinstance(cfg, dict):
                continue
            settings = cfg.get("settings") or {}
            uid = settings.get("uid")
            if not uid:
                continue
            result[uid] = {
                "settings": deepcopy(settings),
                "feeds": deepcopy(cfg.get("feeds") or []),
            }
        return result

    def _default_global(self) -> Dict[str, Any]:
        return {
            key: deepcopy(getattr(config, key))
            for key in GLOBAL_KEYS
            if hasattr(config, key)
        }

    # --------------------------------------------------------------- access

    def list_uids(self) -> List[str]:
        """Return the effective UIDs known to the store."""
        return sorted(self._user_by_uid.keys())

    def get_user(self, uid: str) -> Optional[Dict[str, Any]]:
        """Return the effective per-user block {uid, settings, feeds}, or None."""
        if uid not in self._user_by_uid:
            return None
        block = self._user_by_uid[uid]
        return {
            "uid": uid,
            "settings": deepcopy(block.get("settings", {})),
            "feeds": deepcopy(block.get("feeds", [])),
        }

    def get_user_settings(self, uid: str) -> Optional[Dict[str, Any]]:
        if uid not in self._user_by_uid:
            return None
        return deepcopy(self._user_by_uid[uid].get("settings", {}))

    def get_user_feeds(self, uid: str) -> Optional[List[Dict[str, Any]]]:
        if uid not in self._user_by_uid:
            return None
        return deepcopy(self._user_by_uid[uid].get("feeds", []))

    def get_global(self) -> Dict[str, Any]:
        return deepcopy(self._global)

    # ------------------------------------------------------------ mutation

    def update_user(
        self,
        uid: str,
        settings: Optional[Dict[str, Any]] = None,
        feeds: Optional[List[Dict[str, Any]]] = None,
        global_: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Merge validated settings/feeds/global into the effective config.

        Unknown UIDs are rejected (the web UI only edits existing users).
        Persists afterwards and applies any global changes to the live `config`
        module immediately.
        """
        if uid not in self._user_by_uid:
            return False

        current = self._user_by_uid[uid]
        merged_settings = deepcopy(current.get("settings", {}))
        if isinstance(settings, dict):
            for key, value in settings.items():
                if key in USER_SETTING_KEYS:
                    merged_settings[key] = deepcopy(value)
        if isinstance(feeds, list):
            # The GUI sends the complete feed list (post add/edit/delete).
            current["feeds"] = [deepcopy(f) for f in feeds]
        current["settings"] = merged_settings

        if isinstance(global_, dict) and global_:
            self.update_global(global_)

        self.save()
        return True

    def update_global(self, new_global: Dict[str, Any]) -> None:
        """Merge a partial global block into the effective globals and apply."""
        for key in GLOBAL_KEYS:
            if key in new_global:
                self._global[key] = deepcopy(new_global[key])
        self.apply_global_to_config()

    def apply_global_to_config(self) -> None:
        """Write the effective globals onto the live config module.

        This is what makes runtime changes take effect immediately: modules that
        read `config.XXX` at call time (paywall detector, ML tagger, feedmgr)
        will see the updated values on their next run.
        """
        for key, value in self._global.items():
            setattr(config, key, deepcopy(value))

    # -------------------------------------------------------------- persistence

    def save(self) -> bool:
        """Atomically persist the effective configuration to the JSON file."""
        payload = {
            "version": _RUNTIME_FILE_VERSION,
            "global": {k: deepcopy(v) for k, v in self._global.items()},
            "users": {
                uid: deepcopy(block) for uid, block in self._user_by_uid.items()
            },
        }
        try:
            self._runtime_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._runtime_file.with_suffix(self._runtime_file.suffix + ".tmp")
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(self._runtime_file)
            logger.info("Runtime settings persisted to %s", self._runtime_file)
            return True
        except Exception:
            logger.exception("Failed to persist runtime settings to %s", self._runtime_file)
            return False