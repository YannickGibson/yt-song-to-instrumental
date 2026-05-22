from pathlib import Path

# Directories
DATA_DIR = Path("data")
OUTPUT_DIR = Path("output")
TMP_DIR = Path("tmp")
DB_FILENAME = "history.db"

# Audio formats
SUPPORTED_AUDIO_FORMATS = (".wav", ".flac", ".mp3", ".m4a", ".opus")
DEFAULT_DOWNLOAD_FORMAT = "wav"
FINAL_OUTPUT_FORMAT = "mp3"
FINAL_OUTPUT_BITRATE = "320k"

# Quality thresholds
MIN_DURATION_SECONDS = 30
MAX_SILENCE_RATIO = 0.5
SILENCE_THRESHOLD_DB = -50

# Separator model identifiers
MODEL_DEMUCS = "htdemucs"
MODEL_MDXNET = "mdxnet"
DEFAULT_MODEL = MODEL_DEMUCS
AVAILABLE_MODELS = (MODEL_DEMUCS, MODEL_MDXNET)

MODEL_DISPLAY_NAMES = {
    MODEL_DEMUCS: "HTDemucs",
    MODEL_MDXNET: "MDX-Net",
}

# YouTube upload
YOUTUBE_CATEGORY_MUSIC = "10"
YOUTUBE_PRIVACY_UNLISTED = "unlisted"
YOUTUBE_PRIVACY_PUBLIC = "public"
YOUTUBE_PRIVACY_PRIVATE = "private"
VALID_PRIVACY_STATUSES = (YOUTUBE_PRIVACY_PUBLIC, YOUTUBE_PRIVACY_UNLISTED, YOUTUBE_PRIVACY_PRIVATE)
DEFAULT_PRIVACY_STATUS = YOUTUBE_PRIVACY_PUBLIC
UPLOAD_CHUNK_SIZE_BYTES = 10 * 1024 * 1024
YOUTUBE_TITLE_MAX_LENGTH = 100

# Upload retry behaviour — YouTube's per-account rate limit ("uploadLimitExceeded")
# is a sliding window, so a fixed-delay retry will eventually succeed.
RETRYABLE_UPLOAD_REASONS = ("uploadLimitExceeded", "rateLimitExceeded", "userRateLimitExceeded")
UPLOAD_RETRY_INITIAL_WAIT_SECONDS = 300       # 5 min
UPLOAD_RETRY_MAX_WAIT_SECONDS = 1800          # 30 min cap per attempt
UPLOAD_RETRY_BACKOFF_MULTIPLIER = 2

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

# Strip noise parentheticals (and surrounding whitespace) from track titles —
# e.g. "Lord Of Chaos (Official Music Video)" → "Lord Of Chaos". The negative
# lookahead preserves "(feat. X)" / "(ft. X)" segments because those are credit
# annotations that the collaborator-playlist extractor still needs.
TITLE_PARENTHETICAL_PATTERN = r"\s*\((?!\s*(?:feat\.?|ft\.?)\b)[^)]*\)\s*"

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

ALL_TEMPLATE_TAGS = (
    TAG_ARTIST_NAME,
    TAG_TRACK_TITLE,
    TAG_ALBUM_NAME,
    TAG_ORIGINAL_URL,
    TAG_ORIGINAL_CHANNEL_URL,
    TAG_MODEL_NAME,
    TAG_LABEL_NAME,
    TAG_CHANNEL_URL,
    TAG_ARTIST_TAG,
    TAG_VIDEO_TITLE,
)

# Matches any kebab-case template tag like "<artist-name>". Used by
# validate_template_tags to detect unsupported tags before upload.
TEMPLATE_TAG_PATTERN = r"<[a-z][a-z-]*>"
