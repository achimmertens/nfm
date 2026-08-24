"""Unit tests for app.core.settings_store (runtime settings persistence).

Only needs the stdlib + app.conf.config; no fastapi/feedparser/torch required.
"""

import json

import pytest

from app.conf.config import user_cfgs
from app.core.settings_store import SettingsStore, USER_SETTING_KEYS


@pytest.fixture()
def runtime_file(tmp_path):
    return tmp_path / "runtime-settings.json"


def test_load_defaults_without_file(runtime_file):
    store = SettingsStore(runtime_file=runtime_file, user_cfgs=user_cfgs)
    assert store.list_uids() == ["user01"]
    user = store.get_user("user01")
    assert user["uid"] == "user01"
    # settings/feeds from config.py defaults are present
    assert "highlight_keywords" in user["settings"]
    assert len(user["feeds"]) >= 1
    # global defaults are loaded from the config module
    assert store.get_global()["LIMIT"] == 999


def test_overlay_from_file(runtime_file):
    runtime_file.write_text(
        json.dumps(
            {
                "global": {"HOURS_BACK": 12},
                "users": {
                    "user01": {
                        "settings": {"highlight_keywords": ["python", "esp32"]},
                        "feeds": [
                            {"source": "Test", "url": "http://x/rss", "topic": "Test"}
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    store = SettingsStore(runtime_file=runtime_file, user_cfgs=user_cfgs)
    user = store.get_user("user01")
    assert user["settings"]["highlight_keywords"] == ["python", "esp32"]
    # keys not in the overlay keep their config.py default
    assert user["settings"]["blacklist_link"] == user_cfgs[0]["settings"]["blacklist_link"]
    assert user["feeds"] == [{"source": "Test", "url": "http://x/rss", "topic": "Test"}]
    assert store.get_global()["HOURS_BACK"] == 12


def test_update_user_merge_and_persist(runtime_file):
    store = SettingsStore(runtime_file=runtime_file, user_cfgs=user_cfgs)
    ok = store.update_user(
        "user01",
        settings={"highlight_keywords": ["linux"], "blacklist_link": ["sport"]},
        feeds=[{"source": "Neu", "url": "http://neu/rss", "topic": "T", "check_paywall": True}],
        global_={"LIMIT": 42},
    )
    assert ok is True

    # in-memory state merged
    user = store.get_user("user01")
    assert user["settings"]["highlight_keywords"] == ["linux"]
    assert user["settings"]["blacklist_link"] == ["sport"]
    assert user["feeds"] == [{"source": "Neu", "url": "http://neu/rss", "topic": "T", "check_paywall": True}]

    # global applied to the live config module (runtime effect)
    import app.conf.config as config
    assert config.LIMIT == 42

    # persisted and reloadable
    assert runtime_file.exists()
    store2 = SettingsStore(runtime_file=runtime_file, user_cfgs=user_cfgs)
    user2 = store2.get_user("user01")
    assert user2["settings"]["highlight_keywords"] == ["linux"]
    assert user2["feeds"][0]["check_paywall"] is True


def test_update_unknown_uid_rejected(runtime_file):
    store = SettingsStore(runtime_file=runtime_file, user_cfgs=user_cfgs)
    assert store.update_user("ghost", settings={}) is False
    assert store.get_user("ghost") is None


def test_unknown_settings_keys_ignored(runtime_file):
    store = SettingsStore(runtime_file=runtime_file, user_cfgs=user_cfgs)
    ok = store.update_user("user01", settings={"bogus_key": "x", "highlight_keywords": ["ok"]})
    assert ok is True
    user = store.get_user("user01")
    assert "bogus_key" not in user["settings"]
    assert user["settings"]["highlight_keywords"] == ["ok"]
    assert set(user["settings"].keys()) <= set(USER_SETTING_KEYS)


def test_user_by_uid_attribute_consistency(runtime_file):
    """Regression: __init__/load/accessors must all use the same attribute."""
    store = SettingsStore(runtime_file=runtime_file, user_cfgs=user_cfgs)
    assert hasattr(store, "_user_by_uid")
    # internal dict is the single source of truth
    assert store._user_by_uid["user01"]["settings"]["uid"] == "user01"
    for uid in store.list_uids():
        assert store.get_user(uid) is not None
        assert store.get_user_settings(uid) is not None
        assert store.get_user_feeds(uid) is not None