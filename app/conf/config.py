# Main Configuration file

# Path to the secrets file containing sensitive information (e.g., email credentials)
SECRETS_FILE = "secrets.json"
# Set to True to use precomputed render data for testing
USE_PRECOMPUTED_RENDER_DATA = False
# Number of feeds to fetch
LIMIT = 999
# Number of hours back to consider articles
HOURS_BACK = 24
# Sources to include; empty list means all sources   
SOURCE_FILTER = []
# SOURCE_FILTER = ["Tagesschau", "Der Standard"]

# Enable "Hide Uninteresting Items" functionality for collecting negative ML samples
# When enabled, users can hide unclicked items and record them as negative samples (rating=0)
# This should be disabled in case email distribution
ENABLE_HIDE_UNREAD = True

# Set to True to deploy manifest.json for PWA support
DEPLOY_MANIFEST = False

# Paywall detector settings.

# Score threshold for classifying an article as paywalled.
PAYWALL_SCORE_THRESHOLD = 60
# HTTP timeout for paywall checks (seconds).
PAYWALL_REQUEST_TIMEOUT_SECONDS = 20
# Number of retries on transient network errors (0 = no retry).
PAYWALL_REQUEST_RETRIES = 1
# Optional path for append-only paywalled article HTML output. Set to None to disable writing.
PAYWALL_CLASSIFIED_ARTICLES_HTML_FILE = "misc/paywalled_articles.html"

# Cron job settings for email distribution.
CRONTRIGGER = {"hour": "05", "minute": "55"}

# ML-based tagging of entries similar to previously clicked ("liked") entries.
ML_TAG_ENABLED = True
# Retrain the per-user model once the current clicktrack file exceeds this size (bytes).
ML_RETRAIN_THRESHOLD_BYTES = 1_000_000  # 1 MB
# Sample weight for negative samples (rating=0, "mark as read") relative to a fully
# class-balanced weighting (which is computed automatically from the actual pos/neg
# counts used in training). 1.0 = balanced classes; <1.0 favors recall (more tags,
# more false positives); >1.0 favors precision (fewer, more confident tags).
ML_NEGATIVE_WEIGHT = 1.3
# Cap negative samples per training run at this multiple of the positive sample count.
ML_NEGATIVE_CAP_MULTIPLIER = 10
# Minimum predicted probability for an entry to be tagged as similar to liked entries.
ML_TAG_THRESHOLD = 0.7

# Configuration for user: user01
config_user01 = {
    "settings": {
        "uid": "user01",
        "consumption_modes": ["web"],
        "recipients": [],
        "source_sort_order": {"Spiegel": 10, "Tagesschau": 20, "Heise": 30, "Golem": 40, "T-online": 50, "Stern": 60, "Focus": 70,},
        "blacklist_link": ['sport', 'fussball', 'tennis', 'formel1'],
        "blacklist_title": [
            'dfb-', 'fifa', 'bundesliga', 'fußball', 'football', 'soccer', 'sport', 'fussball', 'nba', 'nfl', 'mlb', 'nhl',
            'tennis', 'cricket', 'rugby', 'volleyball', 'eishockey', 'handball', 'formel 1', 'formel1', 'motorsport',
            'motogp', 'darts', 'boxen', 'kampfsport', 'golf', 'badminton', 'skispringen', 'biathlon', 'leichtathletik',
            'cycling', 'radsport', 'uefa', 'champions league', 'europa league', 'world cup',
            'olympia', 'olympische spiele', 'paralympics',
            'halloween', 'ralf schumacher', 'carmen geiss', 'robert geiss', 'geissens', 'dieter bohlen', 'bushido', 'pooth', 'franjo',
            'heidi klum', 'leni klum', 'gntm', 'next topmodel', 'love island',
            "let's dance", "dancing on ice", "fürstin gloria", "helene fischer", "florian silbereisen", 
            'dschungelcamp', 'ich bin ein star', 'big brother', 'temptation island',
            "dsds", "voice of germany", "the voice kids", "masked singer", "bauer sucht frau",
            'bachelor', 'bachelorette', 'ninja warrior', 'ninja challenge',
            "maybrit illner", "kaulitz", "wer wird millionär", "joko und klaas", "pocher", "schlag den star",
            "kai pflaume", "markus lanz", "joko & klaas", "maxton hall" , "kardashian", "pietro lombardi",
            "harry potter", "rowling", "hogwarts", 
            'polizeiruf 110', '"traumschiff"', 'bridgerton',
            'verbotene liebe', 'gute zeiten schlechte zeiten', 'gzsz', 'sturm der liebe', 'alles was zählt', 'höhle der löwen',
            '(g+)', '(s+)', '[plus]', 'anzeige:', 'heise-angebot:',
            'talkshow', 'talentshow', 'casting show', 'reality show', 'bambi', 'maischberger', '1live krone', 'night of the proms',
            'batman', 'superman', 'spiderman', 'spider-man','avengers', 'wonder woman', 'aquaman', 'superheld', 'superhelden', 'superheldin', 'marvel', 'dc comics', 'comic con', 'comic-con',
            'orden wider den tierischen ernst', 'karlspreis',
            ' esc ', 'eurovision', 'song contest', 'eurovision song contest',
            'orden wider den tierischen ernst', 'bambi', 'grimme-Preis', 'deutscher fernsehpreis',
            'zurück in die zukunft',
        ],
        "highlight_keywords": [
            "python", "jupyter", "esp32",
            "raspberry pi", "raspberrypi", "raspberry-pi", "raspi", "mqtt", "home assistant", "grafana", "influxdb", "node-red",
            "gimp", "fusion 360", "audacity", "notepad++", "winscp", "putty", "vscode", "visual studio code",
            "machine learning", " ki ", " ki-", "künstliche intelligenz", "chatgpt", "openai", "claude", "gemini", "notebooklm", "llm",
            "docker", "ollama", "langchain", "huggingface",
        ],
    },
    "feeds": [
        {"source": "Spiegel", "url": "https://www.spiegel.de/politik/index.rss", "topic": "Politik", "check_paywall": True},
        {"source": "Spiegel", "url": "https://www.spiegel.de/wirtschaft/index.rss", "topic": "Wirtschaft/Finanzen", "check_paywall": True},
        {"source": "Spiegel", "url": "https://www.spiegel.de/panorama/index.rss", "topic": "Panorama", "check_paywall": True},

        {"source": "Tagesschau", "url": "https://www.tagesschau.de/inland/index~rss2.xml", "topic": "Politik - Inland"},
        {"source": "Tagesschau", "url": "https://www.tagesschau.de/ausland/index~rss2.xml", "topic": "Politik - Ausland"},
        {"source": "Tagesschau", "url": "https://www.tagesschau.de/wirtschaft/index~rss2.xml", "topic": "Wirtschaft/Finanzen"},

        {"source": "Heise", "url": "https://www.heise.de/autos/feed.xml", "topic": "Mobilität"},
        {"source": "Heise", "url": "https://www.heise.de/rss/heise-Rubrik-Wirtschaft-atom.xml", "topic": "Wirtschaft/Finanzen"},
        {"source": "Heise", "url": "https://www.heise.de/rss/heise-Rubrik-Wissen-atom.xml", "topic": "Wissen"},

        {"source": "Golem", "url": "https://rss.golem.de/rss.php?ms=auto&feed=ATOM1.0", "topic": "Mobilität", "desc_filter": "golem", "check_paywall": True},
        {"source": "Golem", "url": "https://rss.golem.de/rss.php?ms=mobil&feed=ATOM1.0", "topic": "Mobilität", "desc_filter": "golem", "check_paywall": True},
        {"source": "Golem", "url": "https://rss.golem.de/rss.php?ms=politik-recht&feed=ATOM1.0", "topic": "Politik", "desc_filter": "golem", "check_paywall": True},
 
        {"source": "T-online", "url": "https://www.t-online.de/nachrichten/feed.rss", "topic": "Politik"},
        {"source": "T-online", "url": "https://www.t-online.de/nachrichten/panorama/feed.rss", "topic": "Panorama"},
        {"source": "T-online", "url": "https://www.t-online.de/unterhaltung/feed.rss", "topic": "Unterhaltung"},
  
        {"source": "Stern", "url": "https://www.stern.de/feed/standard/wissen/", "topic": "Wissen", "check_paywall": True},
        {"source": "Stern", "url": "https://www.stern.de/feed/standard/panorama/", "topic": "Panorama", "check_paywall": True},
        {"source": "Stern", "url": "https://www.stern.de/feed/standard/politik/", "topic": "Politik", "check_paywall": True},
 
        {"source": "Focus", "url": "https://www.focus.de/politik/rss", "topic": "Politik", "check_paywall": True},
        {"source": "Focus", "url": "https://www.focus.de/finanzen/rss", "topic": "Wirtschaft/Finanzen", "check_paywall": True},
        {"source": "Focus", "url": "https://www.focus.de/wissen/rss", "topic": "Wissen", "check_paywall": True},

    ],
}

# Configuration for user: user02
config_user02 = {
    "settings": {
        "uid": "user02",
        "consumption_modes": ["web"],
        "recipients": [],
        "source_sort_order": {},
        "blacklist_link": ['sport', 'fussball', 'tennis', 'formel1'],
        "blacklist_title": [
            'dfb-pokal', 'bundesliga', 'fußball', 'football', 'soccer', 'sport', 'fussball', 'nba', 'nfl', 'mlb', 'nhl',
            'tennis', 'cricket', 'rugby', 'volleyball', 'eishockey', 'handball', 'formel 1', 'formel1', 'motorsport',
            'motogp', 'darts', 'boxen', 'kampfsport', 'golf', 'badminton', 'skispringen', 'biathlon', 'leichtathletik',
        ],
        "highlight_keywords": [],
    },
    "feeds": [
        {"source": "Tagesschau", "url": "https://www.tagesschau.de/inland/index~rss2.xml", "topic": "Inland"},
        {"source": "Tagesschau", "url": "https://www.tagesschau.de/ausland/index~rss2.xml", "topic": "Ausland"},
        {"source": "Tagesschau", "url": "https://www.tagesschau.de/wirtschaft/index~rss2.xml", "topic": "Wirtschaft/Finanzen"},
        {"source": "Tagesschau", "url": "https://www.tagesschau.de/wissen/index~rss2.xml", "topic": "Wissen"},
    ],
}

# All configurations
user_cfgs = [config_user01]
