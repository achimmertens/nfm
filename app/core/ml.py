"""ML-based tagging of news entries similar to previously liked ("clicked") entries.

Trains a per-user logistic regression classifier on top of the MiniLM sentence
embeddings (the same model used for deduplication in `app/core/dedup.py`) using
the clicktrack data (`clicktrack_{uid}.jsonl`) as labeled training data:
- rating=1 (clicked)      -> positive sample
- rating=0 (mark-as-read) -> negative sample (down-weighted, see config.ML_NEGATIVE_WEIGHT)

Retraining is triggered when the current clicktrack file exceeds
`config.ML_RETRAIN_THRESHOLD_BYTES`. Training uses all historical data (current
file + archived files in `clicktrack/archiv/`), which are kept indefinitely.
To keep retraining cheap as history grows, MiniLM embeddings are cached on disk
(keyed by link ID) and negative samples are capped at
`config.ML_NEGATIVE_CAP_MULTIPLIER` times the number of positive samples.
"""

import json
import logging
import pickle
import random
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from sklearn.linear_model import LogisticRegression

import app.conf.config as config

logger = logging.getLogger(__name__)

_CLICKTRACK_DIR = Path(__file__).parent.parent.parent / "clicktrack"
_ARCHIVE_DIR = _CLICKTRACK_DIR / "archiv"
_MODELS_DIR = _CLICKTRACK_DIR / "models"


def _clicktrack_file_fq(uid: str) -> Path:
    return _CLICKTRACK_DIR / f"clicktrack_{uid}.jsonl"


def _model_file_fq(uid: str) -> Path:
    return _MODELS_DIR / f"model_{uid}.pkl"


def _embeddings_cache_file_fq(uid: str) -> Path:
    return _MODELS_DIR / f"embeddings_{uid}.pkl"


def _archived_files(uid: str) -> List[Path]:
    """Return archived clicktrack files for a user, sorted chronologically (oldest first)."""
    if not _ARCHIVE_DIR.exists():
        return []
    return sorted(_ARCHIVE_DIR.glob(f"*_clicktrack_{uid}.jsonl"))


def _get_semantic_model(semantic_model=None):
    """Return the given semantic model, or lazily create one if none was provided."""
    if semantic_model is not None:
        return semantic_model
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    model.to("cpu")
    return model


def _entry_text(title: str, description: str) -> str:
    return f"{title or ''} {description or ''}".strip()


class MLTagger:
    """Tags news entries as similar to previously clicked entries, using a per-user model."""

    def __init__(self, uid: str, semantic_model=None, tag_threshold: float = None):
        self._uid = uid
        self._semantic_model = semantic_model
        self._tag_threshold = tag_threshold if tag_threshold is not None else config.ML_TAG_THRESHOLD
        self.classifier = None

        model_fq = _model_file_fq(uid)
        if model_fq.exists():
            try:
                with open(model_fq, "rb") as f:
                    self.classifier = pickle.load(f)
            except Exception:
                logger.exception(f"[{uid}] Failed to load ML model from {model_fq}")
                self.classifier = None

    def tag_stories(self, stories_by_lid: Dict[str, Dict]) -> int:
        """Tags non-duplicate stories predicted similar to liked entries.

        Sets `is_ml_tagged=True` and `ml_score_pct=<int percentage>` on stories whose
        predicted probability exceeds the tag threshold.

        Args:
            stories_by_lid: Dict of story dicts, keyed by link ID.

        Returns:
            int: Number of stories tagged.
        """
        if self.classifier is None:
            return 0

        candidates = [
            (lid, story) for lid, story in stories_by_lid.items()
            if not story.get("is_duplicate", False)
        ]
        if not candidates:
            return 0

        semantic_model = _get_semantic_model(self._semantic_model)
        texts = [_entry_text(story["title"], story["description"]) for _, story in candidates]
        embeddings = semantic_model.encode(texts, show_progress_bar=False)

        probabilities = self.classifier.predict_proba(embeddings)[:, 1]

        n_tagged = 0
        for (lid, story), probability in zip(candidates, probabilities):
            if probability > self._tag_threshold:
                story["is_ml_tagged"] = True
                story["ml_score_pct"] = int(round(probability * 100))
                n_tagged += 1

        return n_tagged


def _load_records(file_fq: Path) -> List[dict]:
    """Load JSONL clicktrack records from a single file, skipping malformed lines."""
    records = []
    if not file_fq.exists():
        return records
    with open(file_fq, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def _load_all_labeled_records(uid: str) -> Dict[str, dict]:
    """Loads all clicktrack records (archived + current), applying last-rating-wins per lid."""
    latest_by_lid: Dict[str, dict] = {}
    for file_fq in _archived_files(uid) + [_clicktrack_file_fq(uid)]:
        for record in _load_records(file_fq):
            lid = record.get("lid")
            if lid:
                latest_by_lid[lid] = record  # last write wins (files processed chronologically)
    return latest_by_lid


def _load_embeddings_cache(uid: str) -> Dict[str, np.ndarray]:
    cache_fq = _embeddings_cache_file_fq(uid)
    if not cache_fq.exists():
        return {}
    try:
        with open(cache_fq, "rb") as f:
            return pickle.load(f)
    except Exception:
        logger.exception(f"[{uid}] Failed to load embedding cache from {cache_fq}")
        return {}


def _save_embeddings_cache(uid: str, cache: Dict[str, np.ndarray]) -> None:
    _MODELS_DIR.mkdir(parents=True, exist_ok=True)
    with open(_embeddings_cache_file_fq(uid), "wb") as f:
        pickle.dump(cache, f)


def _archive_clicktrack_file(uid: str) -> None:
    """Archives the current clicktrack file and starts a fresh, empty one."""
    _ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    current_fq = _clicktrack_file_fq(uid)
    if current_fq.exists():
        timestamp = datetime.now().strftime("%y%m%d_%H%M%S")
        archive_fq = _ARCHIVE_DIR / f"{timestamp}_clicktrack_{uid}.jsonl"
        current_fq.rename(archive_fq)
        logger.info(f"[{uid}] Archived clicktrack file to {archive_fq}")
    current_fq.touch()


def _build_training_data(uid: str, semantic_model) -> Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Builds (X, y, sample_weight) arrays for training, using/updating the embedding cache."""
    labeled_records = _load_all_labeled_records(uid)
    if not labeled_records:
        return None

    embeddings_cache = _load_embeddings_cache(uid)

    # Encode any records not yet in the cache, in a single batch call.
    missing_lids = [lid for lid in labeled_records if lid not in embeddings_cache]
    if missing_lids:
        texts = [
            _entry_text(labeled_records[lid].get("title", ""), labeled_records[lid].get("description", ""))
            for lid in missing_lids
        ]
        new_embeddings = semantic_model.encode(texts, show_progress_bar=False)
        for lid, embedding in zip(missing_lids, new_embeddings):
            embeddings_cache[lid] = np.asarray(embedding, dtype=np.float32)
        _save_embeddings_cache(uid, embeddings_cache)

    positive_lids = [lid for lid, r in labeled_records.items() if int(r.get("rating", 1)) == 1]
    negative_lids = [lid for lid, r in labeled_records.items() if int(r.get("rating", 1)) == 0]

    n_positives_pre, n_negatives_pre = len(positive_lids), len(negative_lids)

    # Cap negatives to keep training cost bounded as history grows.
    max_negatives = max(n_positives_pre, 1) * config.ML_NEGATIVE_CAP_MULTIPLIER
    if len(negative_lids) > max_negatives:
        negative_lids = random.sample(negative_lids, max_negatives)

    logger.info(
        f"[{uid}] ML training data: {n_positives_pre} positive, "
        f"{n_negatives_pre} negative (capped to {len(negative_lids)})"
    )

    if n_positives_pre == 0 or n_negatives_pre == 0:
        logger.warning(f"[{uid}] Not enough classes to train ML model (need both positive and negative samples)")
        return None

    lids = positive_lids + negative_lids
    X = np.array([embeddings_cache[lid] for lid in lids])
    y = np.array([int(labeled_records[lid].get("rating", 1)) for lid in lids])

    # Base negative weight that equalizes the *total* weight of both classes (i.e. what
    # sklearn's class_weight="balanced" would compute), scaled by config.ML_NEGATIVE_WEIGHT
    # as a fine-tuning multiplier (1.0 = fully balanced, <1.0 favors recall, >1.0 favors
    # precision). Negatives typically outnumber positives 10:1+ even after capping, so a
    # fixed weight like 0.6 barely dents that imbalance and leaves predicted probabilities
    # for true positives far below any reasonable tagging threshold.
    balanced_negative_weight = len(positive_lids) / len(negative_lids)
    sample_weight = np.where(y == 1, 1.0, balanced_negative_weight * config.ML_NEGATIVE_WEIGHT)

    return X, y, sample_weight


def _train_and_persist(uid: str, semantic_model) -> bool:
    """Trains and persists a logistic regression model for the given user.

    Returns:
        bool: True if a model was trained and saved, False if skipped (e.g. not enough data).
    """
    training_data = _build_training_data(uid, semantic_model)
    if training_data is None:
        return False

    X, y, sample_weight = training_data
    classifier = LogisticRegression(max_iter=1000)
    classifier.fit(X, y, sample_weight=sample_weight)

    _MODELS_DIR.mkdir(parents=True, exist_ok=True)
    with open(_model_file_fq(uid), "wb") as f:
        pickle.dump(classifier, f)

    logger.info(f"[{uid}] ML model trained and saved ({len(y)} samples)")
    return True


def maybe_retrain(uid: str, semantic_model=None, force: bool = False) -> bool:
    """Checks the clicktrack file size and retrains the ML model if the threshold is exceeded.

    On retraining (whether or not a model was actually produced), the current clicktrack
    file is archived and a fresh, empty one is started - this avoids re-evaluating an
    oversized file on every subsequent run.

    Args:
        uid: User ID.
        semantic_model: Optional pre-loaded SentenceTransformer instance to reuse.
        force: If True, retrain regardless of file size (useful for manual testing).

    Returns:
        bool: True if retraining was triggered (regardless of whether a model was saved).
    """
    current_fq = _clicktrack_file_fq(uid)
    if not force:
        if not current_fq.exists() or current_fq.stat().st_size < config.ML_RETRAIN_THRESHOLD_BYTES:
            return False

    logger.info(f"[{uid}] ML retraining triggered")
    model = _get_semantic_model(semantic_model)
    _train_and_persist(uid, model)
    _archive_clicktrack_file(uid)
    return True
