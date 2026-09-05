from pathlib import Path

# Directories
DATA_DIR = Path("data")
OUTPUT_DIR = Path("output")
TMP_DIR = Path("tmp")
DB_FILENAME = "history.db"

# Priority instrumental request queue
PRIORITY_STATUS_PENDING = "pending"
PRIORITY_STATUS_PROCESSING = "processing"
PRIORITY_STATUS_COMPLETED = "completed"
PRIORITY_STATUS_FAILED = "failed"
PRIORITY_SUCCESS_TRACK_STATUSES = ("uploaded", "already_uploaded")
PRIORITY_ERROR_NO_TRACK = "The requested URL produced no uploadable track"
PRIORITY_ERROR_REPORT_PREFIX = "Pipeline did not complete: "
YOUTUBE_CANONICAL_VIDEO_URL = "https://www.youtube.com/watch?v={video_id}"
YOUTUBE_VIDEO_ID_PATTERN = r"^[A-Za-z0-9_-]{11}$"

# Audio formats
SUPPORTED_AUDIO_FORMATS = (".wav", ".flac", ".mp3", ".m4a", ".opus")
DEFAULT_DOWNLOAD_FORMAT = "wav"
FINAL_OUTPUT_FORMAT = "mp3"
FINAL_OUTPUT_BITRATE = "320k"

# Quality thresholds
MIN_DURATION_SECONDS = 30
MAX_SILENCE_RATIO = 0.5
SILENCE_THRESHOLD_DB = -50

# Trimming configurations
DEFAULT_TRIM_SILENCE = True
DEFAULT_TRIM_THRESHOLD_DB = -35.0
DEFAULT_TRIM_MIN_DURATION_SECONDS = 0.5
DEFAULT_TRIM_MIN_SUSTAINED_SECONDS = 0.3



# Separator model identifiers
MODEL_DEMUCS = "htdemucs"
MODEL_INST_HQ_4 = "inst_hq_4"
DEFAULT_MODEL = MODEL_DEMUCS
AVAILABLE_MODELS = (MODEL_DEMUCS, MODEL_INST_HQ_4)

MODEL_DISPLAY_NAMES = {
    MODEL_DEMUCS: "HTDemucs",
    MODEL_INST_HQ_4: "UVR-MDX-NET Inst_HQ_4",
}

# Inst_HQ_4 (UVR-MDX-NET) — ONNX-based 2-stem (vocals/instrumental) separator.
# The model file is fetched by audio-separator on first use into AUDIO_SEPARATOR_MODELS_DIR.
INST_HQ_4_MODEL_FILE = "UVR-MDX-NET-Inst_HQ_4.onnx"
AUDIO_SEPARATOR_MODELS_DIR = "data/audio_separator_models"

# YouTube upload
YOUTUBE_CATEGORY_MUSIC = "10"
YOUTUBE_PRIVACY_UNLISTED = "unlisted"
YOUTUBE_PRIVACY_PUBLIC = "public"
YOUTUBE_PRIVACY_PRIVATE = "private"
VALID_PRIVACY_STATUSES = (YOUTUBE_PRIVACY_PUBLIC, YOUTUBE_PRIVACY_UNLISTED, YOUTUBE_PRIVACY_PRIVATE)
DEFAULT_PRIVACY_STATUS = YOUTUBE_PRIVACY_PUBLIC
UPLOAD_CHUNK_SIZE_BYTES = 10 * 1024 * 1024
YOUTUBE_TITLE_MAX_LENGTH = 100

# Upload retry behaviour — YouTube's per-account rate limit
# ("uploadLimitExceeded") is a sliding window, so a delayed retry eventually
# succeeds. The schedule is a tuned ladder: short waits give a fast probe,
# longer waits avoid hammering the API once the window is clearly saturated.
# Past the end of the schedule, the final value (2 h) repeats indefinitely.
RETRYABLE_UPLOAD_REASONS = ("uploadLimitExceeded", "rateLimitExceeded", "userRateLimitExceeded")
UPLOAD_RETRY_BACKOFF_SCHEDULE_SECONDS = (
    600,    # 10 min — first retry
    1800,   # 30 min
    3600,   # 1 hour
    7200,   # 2 hours — and repeats from here on
)

# YouTube API scopes
YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
YOUTUBE_SCOPE = "https://www.googleapis.com/auth/youtube"
YOUTUBE_READONLY_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"

# Thumbnail resolution fallback order (yt-dlp thumbnail keys)
THUMBNAIL_RESOLUTION_ORDER = ("maxresdefault", "sddefault", "hqdefault", "mqdefault", "default")

# yt-dlp
YTDLP_FORMAT = "bestaudio/best"
YTDLP_RETRIES = 3

# Video rendering (ffmpeg)
VIDEO_CODEC = "libx264"
VIDEO_PIXEL_FORMAT = "yuv420p"
VIDEO_CRF = "18"
AUDIO_CODEC = "aac"
AUDIO_BITRATE = "320k"

# Label config file
LABEL_CONFIG_FILENAME = "label.yml"
LABEL_CONFIG_EXAMPLE_FILENAME = "label.yml.example"

# Source after_date format: YYYYMMDD
AFTER_DATE_PATTERN = r"^\d{8}$"

# Topic channel suffix regex pattern: " - Topic", " – Topic", " — Topic"
TOPIC_SUFFIX_PATTERN = r"\s*[\-–—]\s*topic$"

# Strip noise parentheticals (and surrounding whitespace) from track titles —

# e.g. "Lord Of Chaos (Official Music Video)" → "Lord Of Chaos". The negative
# lookahead preserves "(feat. X)" / "(ft. X)" segments because those are credit
# annotations that the collaborator-playlist extractor still needs.
TITLE_PARENTHETICAL_PATTERN = r"\s*\((?!\s*(?:feat\.?|ft\.?)\b)[^)]*\)\s*"

# YouTube Shorts constants
SHORT_DURATION_SECONDS = 20.0
SHORT_VIDEO_HEIGHT = 1920
SHORT_VIDEO_WIDTH = 1080
SHORT_CONTENT_HEIGHT = 1152
SHORT_BAR_HEIGHT = 384
SHORT_DEFAULT_MOTION_THRESHOLD = 10.0
SHORT_VIDEO_CRF = "20"
SHORT_PRESET = "ultrafast"
SHORT_TITLE_SUFFIX = "(Instrumental Teaser)"

# Template tags
TAG_ARTIST_NAME = "<artist-name>"
TAG_TRACK_TITLE = "<track-title>"
TAG_ALBUM_NAME = "<album-name>"
TAG_ORIGINAL_URL = "<original-url>"
TAG_ORIGINAL_CHANNEL_URL = "<original-channel-url>"
TAG_MODEL_NAME = "<model-name>"
TAG_LABEL_NAME = "<label-name>"
TAG_ARTIST_TAG = "<artist-tag>"
TAG_CHANNEL_URL = "<channel-url>"
TAG_VIDEO_TITLE = "<video-title>"  # the final, rendered upload title
TAG_CHANNEL_NAME = "<channel-name>"  # the label's own YouTube channel display name
TAG_FULL_VIDEO_URL = "<full-video-url>"  # URL to uploaded full instrumental video

ALL_TEMPLATE_TAGS = (
    TAG_ARTIST_NAME,
    TAG_TRACK_TITLE,
    TAG_ALBUM_NAME,
    TAG_ORIGINAL_URL,
    TAG_ORIGINAL_CHANNEL_URL,
    TAG_MODEL_NAME,
    TAG_LABEL_NAME,
    TAG_CHANNEL_URL,
    TAG_CHANNEL_NAME,
    TAG_ARTIST_TAG,
    TAG_VIDEO_TITLE,
    TAG_FULL_VIDEO_URL,
)

# Matches any kebab-case template tag like "<artist-name>". Used by
# validate_template_tags to detect unsupported tags before upload.
TEMPLATE_TAG_PATTERN = r"<[a-z][a-z-]*>"
