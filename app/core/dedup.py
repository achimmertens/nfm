"""Story (article) deduplication logic.

Artikel-Duplikaterkennung für Newsfeed
Optimiert für Raspberry Pi 3
"""

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sentence_transformers import SentenceTransformer
from typing import Dict, List, Tuple, Set
import pickle
from datetime import datetime
from pathlib import Path
import re
import json
import logging

logger = logging.getLogger(__name__)


class StoryDuplicateDetector:
    """
    Zwei-stufiges Modell zur Erkennung von Artikeln mit gleichem Inhalt.
    Optimiert für Raspberry Pi 3.
    """
    
    def __init__(self, 
                 tfidf_threshold: float = 0.3,
                 semantic_threshold: float = 0.75,
                 use_semantic: bool = True,
                 time_window_hours: int = 72,
                 german_stopwords_fq: Path = None,
                 uid: str = "???"):
        """
        Args:
            tfidf_threshold: Schwellwert für TF-IDF Ähnlichkeit (Pre-Filter)
            semantic_threshold: Schwellwert für semantische Ähnlichkeit
            use_semantic: Ob Sentence-BERT genutzt werden soll
            time_window_hours: Zeitfenster für Artikel-Vergleich
            german_stopwords_fq: Pfad zu deutschen Stoppwörtern
        """
        self.tfidf_threshold = tfidf_threshold
        self.semantic_threshold = semantic_threshold
        self.time_window_hours = time_window_hours
        self._uid = uid
        
        # Lade deutsche Stoppwörter
        if german_stopwords_fq is None:
            german_stopwords_fq = Path(__file__).parent.parent.parent / "aux_data" / "german_stopwords.json"
        
        with open(german_stopwords_fq, 'r', encoding='utf-8') as f:
            german_stopwords = json.load(f)

        # TF-IDF Vectorizer (Stufe 1)
        self.vectorizer = TfidfVectorizer(
            max_features=5000,
            ngram_range=(1, 2),
            stop_words=german_stopwords,
            min_df=2,
            max_df=0.8
        )
        
        # Sentence-BERT (Stufe 2) - leichtgewichtiges Modell
        self.semantic_model = None
        if use_semantic:
            try:
                # Sehr kompaktes deutsches Modell (~80MB)
                self.semantic_model = SentenceTransformer(
                    'paraphrase-multilingual-MiniLM-L12-v2'
                )
                # Für CPU optimieren
                self.semantic_model.to('cpu')
            except Exception as e:
                logger.warning(f"[{self._uid}] Semantic Model konnte nicht geladen werden: {e}")
                logger.warning(f"[{self._uid}] Verwende nur TF-IDF.")
    
    def preprocess_text(self, text: str) -> str:
        """Einfache Textvorverarbeitung"""
        if not text:
            return ""
        # Lowercase und Sonderzeichen entfernen
        text = text.lower()
        text = re.sub(r'[^\w\s]', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    
    def combine_article_text(self, story: Dict) -> str:
        """Kombiniert relevante Textfelder eines Artikels"""
        parts = []
        
        # Titel hat höchstes Gewicht (3x)
        if story.get('title'):
            parts.extend([story['title']] * 3)
        
        # Description (2x)
        if story.get('description'):
            parts.extend([story['description']] * 2)
        
        # Topic (1x)
        if story.get('topic'):
            parts.append(story['topic'])
        
        combined = ' '.join(parts)
        return self.preprocess_text(combined)
    
    def filter_by_time(self, stories: Dict, 
                       reference_date: datetime = None) -> Dict:
        """
        Filtert Artikel nach Zeitfenster.
        Nur Artikel im Zeitfenster werden verglichen.
        """
        if reference_date is None:
            reference_date = datetime.now()
        
        filtered = {}
        for story_id, story in stories.items():
            try:
                pub_date = datetime.fromisoformat(story['pub_date'])
                time_diff = abs((reference_date - pub_date).total_seconds() / 3600)
                
                if time_diff <= self.time_window_hours:
                    filtered[story_id] = story
            except Exception:
                # Bei Parsing-Fehler: Artikel einbeziehen
                filtered[story_id] = story
        
        return filtered
    
    def find_duplicates_tfidf(self, stories: Dict) -> List[Tuple[str, str, float]]:
        """
        Stufe 1: TF-IDF basierte Duplikaterkennung (schnell)
        
        Returns:
            Liste von (story_id1, story_id2, similarity_score)
        """
        story_ids = list(stories.keys())
        
        # Mindestens 2 Artikel erforderlich für Vergleich
        if len(story_ids) < 2:
            return []
        
        # Texte vorbereiten
        texts = [self.combine_article_text(stories[sid]) for sid in story_ids]
        
        # Dynamische Parameter basierend auf Anzahl der Dokumente
        n_docs = len(texts)
        min_df = min(2, max(1, n_docs // 5))  # min_df adaptiv, mindestens 1
        max_df = 0.8 if n_docs > 5 else 1.0   # Bei wenigen Docs: keine max_df Einschränkung
        
        # Vectorizer mit dynamischen Parametern erstellen
        vectorizer = TfidfVectorizer(
            max_features=5000,
            ngram_range=(1, 2),
            stop_words=self.vectorizer.stop_words,
            min_df=min_df,
            max_df=max_df
        )
        
        # TF-IDF Matrix berechnen
        tfidf_matrix = vectorizer.fit_transform(texts)
        
        # Cosine Similarity berechnen
        similarity_matrix = cosine_similarity(tfidf_matrix)
        
        # Kandidatenpaare extrahieren
        candidates = []
        n = len(story_ids)
        
        for i in range(n):
            for j in range(i + 1, n):
                sim = similarity_matrix[i, j]
                if sim >= self.tfidf_threshold:
                    candidates.append((story_ids[i], story_ids[j], sim))
        
        # Nach Ähnlichkeit sortieren
        candidates.sort(key=lambda x: x[2], reverse=True)
        return candidates
    
    def find_duplicates_semantic(self, stories: Dict, 
                                 candidates: List[Tuple[str, str, float]]) -> List[Tuple[str, str, float]]:
        """
        Stufe 2: Semantische Duplikaterkennung mit Sentence-BERT
        Nur für vielversprechende Kandidaten aus Stufe 1
        
        Returns:
            Liste von (story_id1, story_id2, similarity_score)
        """
        if not self.semantic_model or not candidates:
            return candidates
        
        duplicates = []
        
        # Batch-Verarbeitung für Effizienz
        batch_size = 16
        
        for i in range(0, len(candidates), batch_size):
            batch = candidates[i:i + batch_size]
            
            # Texte für Batch vorbereiten
            texts_a = [self.combine_article_text(stories[c[0]]) for c in batch]
            texts_b = [self.combine_article_text(stories[c[1]]) for c in batch]
            
            # Embeddings berechnen
            embeddings_a = self.semantic_model.encode(texts_a, convert_to_tensor=False)
            embeddings_b = self.semantic_model.encode(texts_b, convert_to_tensor=False)
            
            # Cosine Similarity für jedes Paar
            for idx, (story_id1, story_id2, tfidf_sim) in enumerate(batch):
                emb_a = embeddings_a[idx].reshape(1, -1)
                emb_b = embeddings_b[idx].reshape(1, -1)
                
                semantic_sim = cosine_similarity(emb_a, emb_b)[0, 0]
                
                if semantic_sim >= self.semantic_threshold:
                    duplicates.append((story_id1, story_id2, semantic_sim))
        
        duplicates.sort(key=lambda x: x[2], reverse=True)
        return duplicates
    
    def find_all_duplicates(self, stories: Dict) -> List[Tuple[str, str, float]]:
        """
        Hauptmethode: Findet alle Duplikate im Artikelpool
        
        Returns:
            Liste von (story_id1, story_id2, similarity_score)
        """
        # Nach Zeit filtern
        filtered_stories = self.filter_by_time(stories)
        
        logger.info(f"[{self._uid}] Analysiere {len(filtered_stories)} Artikel im Zeitfenster...")
        
        # Stufe 1: TF-IDF Pre-Filtering
        logger.info(f"[{self._uid}] Stufe 1: TF-IDF Pre-Filtering...")
        candidates = self.find_duplicates_tfidf(filtered_stories)
        logger.info(f"[{self._uid}] Stufe 1: {len(candidates)} Kandidatenpaare gefunden")
        
        # Stufe 2: Semantische Analyse
        if self.semantic_model and candidates:
            logger.info(f"[{self._uid}] Stufe 2: Semantische Analyse...")
            duplicates = self.find_duplicates_semantic(filtered_stories, candidates)
            logger.info(f"[{self._uid}] Stufe 2: {len(duplicates)} Duplikate bestätigt")
        else:
            duplicates = candidates
        
        return duplicates
    
    def get_duplicate_clusters(self, duplicates: List[Tuple[str, str, float]]) -> List[Set[str]]:
        """
        Gruppiert Duplikate in Cluster (transitive Hülle)
        
        Returns:
            Liste von Sets, wobei jedes Set eine Gruppe von Duplikaten ist
        """
        # Union-Find Datenstruktur
        parent = {}
        
        def find(x):
            if x not in parent:
                parent[x] = x
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]
        
        def union(x, y):
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py
        
        # Alle Paare verbinden
        for story_id1, story_id2, _ in duplicates:
            union(story_id1, story_id2)
        
        # Cluster bilden
        clusters = {}
        for story_id in parent:
            root = find(story_id)
            if root not in clusters:
                clusters[root] = set()
            clusters[root].add(story_id)
        
        # Nur Cluster mit mehr als 1 Element zurückgeben
        return [cluster for cluster in clusters.values() if len(cluster) > 1]
    
    def save_model(self, filepath: str):
        """Speichert das Modell"""
        model_data = {
            'vectorizer': self.vectorizer,
            'tfidf_threshold': self.tfidf_threshold,
            'semantic_threshold': self.semantic_threshold,
            'time_window_hours': self.time_window_hours
        }
        with open(filepath, 'wb') as f:
            pickle.dump(model_data, f)
        logger.info(f"[{self._uid}] Modell gespeichert: {filepath}")
    
    @classmethod
    def load_model(cls, filepath: str, use_semantic: bool = True):
        """Lädt ein gespeichertes Modell"""
        with open(filepath, 'rb') as f:
            model_data = pickle.load(f)
        
        detector = cls(
            tfidf_threshold=model_data['tfidf_threshold'],
            semantic_threshold=model_data['semantic_threshold'],
            use_semantic=use_semantic,
            time_window_hours=model_data['time_window_hours']
        )
        detector.vectorizer = model_data['vectorizer']
        return detector
