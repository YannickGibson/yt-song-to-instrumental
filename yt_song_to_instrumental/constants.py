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
PRIORITY_ERROR_REQUESTED_OUTPUTS = (
    "Requested long-form instrumental and Short were not both completed"
)
PRIORITY_DEFAULT_SHORT_START_SECONDS = None
PRIORITY_MIN_SHORT_START_SECONDS = 0.0
PRIORITY_ERROR_SHORT_START_NEGATIVE = "Short start time must be zero or greater"
PRIORITY_ERROR_SHORT_START_REQUIRES_SHORT = "A Short start time requires upload_short=True"
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
MODEL_MEL_GABOX = "mel_gabox_instv7n"
DEFAULT_MODEL = MODEL_DEMUCS
AVAILABLE_MODELS = (MODEL_DEMUCS, MODEL_INST_HQ_4, MODEL_MEL_GABOX)

MODEL_DISPLAY_NAMES = {
    MODEL_DEMUCS: "HTDemucs",
    MODEL_INST_HQ_4: "UVR-MDX-NET Inst_HQ_4",
    MODEL_MEL_GABOX: "MelBand RoFormer INSTV7N",
}

# Inst_HQ_4 (UVR-MDX-NET) — ONNX-based 2-stem (vocals/instrumental) separator.
# The model file is fetched by audio-separator on first use into AUDIO_SEPARATOR_MODELS_DIR.
INST_HQ_4_MODEL_FILE = "UVR-MDX-NET-Inst_HQ_4.onnx"
AUDIO_SEPARATOR_MODELS_DIR = "data/audio_separator_models"

# MPS instrumental backend. Memory is an estimate, not a measured minimum
# across devices and song lengths.
MEL_GABOX_MODEL_FILE = "mel_band_roformer_instrumental_instv7n_gabox.ckpt"
MEL_GABOX_MEMORY_GB = 8.0
MEL_GABOX_GPU_REQUIRED = True
MEL_GABOX_CPU_THREADS = 2
MEL_GABOX_DEVICE = "mps"
MEL_GABOX_PRECISION = "native_fp16"
MEL_GABOX_CACHE_ENV = "AUDIO_SEPARATOR_MODEL_DIR"
MEL_GABOX_OUTPUT_STEM = "Instrumental"
MEL_GABOX_OUTPUT_BASENAME = "instrumental"
MEL_GABOX_OUTPUT_FILENAME = "no_vocals.wav"
MEL_GABOX_OUTPUT_COUNT = 1
MEL_GABOX_TEMP_PREFIX = "mel_gabox_"
MEL_GABOX_VALIDATION_BLOCK_SIZE = 65536
MEL_GABOX_VALIDATION_DTYPE = "float32"
MEL_GABOX_DURATION_TOLERANCE_SECONDS = 0.1
MEL_GABOX_BINARY_READ_MODE = "rb"
MEL_GABOX_SEPARATOR_OPTIONS = {
    "output_format": "WAV",
    "output_single_stem": MEL_GABOX_OUTPUT_STEM,
    "use_soundfile": True,
    "use_autocast": False,
    "use_native_fp16": True,
    "normalization_threshold": 1.0,
    "amplification_threshold": 0.0,
}
MEL_GABOX_MDXC_OPTIONS = {
    "segment_size": 256,
    "override_model_segment_size": False,
    "batch_size": 1,
    "overlap": 4,
    "pitch_shift": 0,
}
MEL_GABOX_NO_DEVICE_ERROR = "The selected instrumental preset requires an available MPS device"
MEL_GABOX_DEVICE_ERROR = "Separator did not load on the required MPS device"
MEL_GABOX_PRECISION_ERROR = "Separator did not activate the required native FP16 precision"
MEL_GABOX_OUTPUT_ERROR = "Separator must produce exactly one instrumental stem inside its temporary directory"
MEL_GABOX_EMPTY_ERROR = "Separator produced an empty or silent instrumental"
MEL_GABOX_NONFINITE_ERROR = "Separator produced non-finite instrumental samples"
MEL_GABOX_DURATION_ERROR = "Instrumental duration differs from its source"

HISTORY_EXISTING_UPLOAD_QUERY = (
    "SELECT * FROM uploads WHERE video_id = ? AND youtube_upload_id != '' "
    "ORDER BY uploaded_at, id LIMIT 1"
)
TRACK_STATUS_ALREADY_UPLOADED = "already_uploaded"
SHORT_SKIPPED_STATUSES = ("skipped_not_music_video", "skipped_disabled")

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
SHORT_START_FRACTION = 0.10
SHORT_DEFAULT_START_SECONDS = 0.0
SHORT_VIDEO_HEIGHT = 1920
SHORT_VIDEO_WIDTH = 1080
SHORT_CONTENT_HEIGHT = 1152
SHORT_BAR_HEIGHT = 384
SHORT_DEFAULT_MOTION_THRESHOLD = 10.0
SHORT_DIVERSITY_SAMPLE_COUNT = 8
SHORT_DIVERSITY_BLUR_RADIUS = 5.0
SHORT_DIVERSITY_MIN_MEDIAN_DIFF = 15.0
SHORT_DIVERSITY_MAX_MEDIAN_CORRELATION = 0.95
SHORT_VIDEO_CRF = "20"
SHORT_PRESET = "ultrafast"
SHORT_TITLE_SUFFIX = "(Instrumental Teaser)"
SHORT_ALTERNATE_SOURCE_MARKER = "_alternate"

# Match the original release to the music-video soundtrack before rendering.
SHORT_ALIGNMENT_FAILED = "audio_alignment_failed"
SHORT_ALIGNMENT_SAMPLE_RATE = 8000
SHORT_ALIGNMENT_WINDOW_SAMPLES = 512
SHORT_ALIGNMENT_HOP_SAMPLES = 128
SHORT_ALIGNMENT_BANDS = 32
SHORT_ALIGNMENT_LOW_HZ = 100
SHORT_ALIGNMENT_HIGH_HZ = 3900
SHORT_ALIGNMENT_SMOOTH_FRAMES = 63
SHORT_ALIGNMENT_SMOOTH_MODE = "same"
SHORT_ALIGNMENT_EPSILON = 1e-8
SHORT_ALIGNMENT_MIN_RMS = 1e-5
SHORT_ALIGNMENT_MAX_SECONDS = 900
SHORT_ALIGNMENT_TIMEOUT_SECONDS = 90
SHORT_ALIGNMENT_MIN_SCORE = 0.80
SHORT_ALIGNMENT_MIN_BLOCK_SCORE = 0.65
SHORT_ALIGNMENT_MIN_MARGIN = 0.06
SHORT_ALIGNMENT_PEAK_EXCLUSION_SECONDS = 0.5
SHORT_ALIGNMENT_BLOCK_SECONDS = 1.0
SHORT_ALIGNMENT_LOCAL_SEARCH_SECONDS = 0.25
SHORT_ALIGNMENT_MAX_DRIFT_SECONDS = 0.032
SHORT_ALIGNMENT_CANDIDATE_STEP_SECONDS = 10.0
SHORT_ALIGNMENT_MAX_CANDIDATES = 12
SHORT_ALIGNMENT_PCM_DTYPE = "<f4"
SHORT_ALIGNMENT_AUDIO_SUFFIX = ".wav"
SHORT_ALIGNMENT_DECODE_COMMAND = (
    "ffmpeg", "-v", "error", "-threads", "1", "-i",
)
SHORT_ALIGNMENT_DECODE_OPTIONS = (
    "-vn", "-sn", "-ac", "1", "-ar", str(SHORT_ALIGNMENT_SAMPLE_RATE),
    "-t", str(SHORT_ALIGNMENT_MAX_SECONDS + 1), "-f", "f32le", "pipe:1",
)
SHORT_ALIGNMENT_DECODE_ERROR = "Could not decode soundtrack for Short alignment"
SHORT_ALIGNMENT_INPUT_ERROR = "Missing, silent, invalid or over-limit Short alignment audio"
SHORT_ALIGNMENT_NO_MATCH = "No unambiguous continuous soundtrack match; holding Short"
SHORT_ALIGNMENT_MATCH_LOG = (
    "Short audio match: video=%.3fs release=%.3fs instrumental=%.3fs "
    "score=%.3f weakest_block=%.3f margin=%.3f"
)
SHORT_ALIGNMENT_REFERENCE_ERROR = "Original audio unavailable; holding Short for %s"
SHORT_ALIGNMENT_ERROR_LOG = "Short audio alignment failed for %s: %s"

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

# Release grouping prefixes
ALBUM_GROUP_PREFIX = "album:"
SINGLE_GROUP_PREFIX = "single:"


# Conservative Short source validation and title formatting.
SHORT_SOURCE_TITLE_PART = "snippet"
SHORT_SOURCE_METADATA_UNAVAILABLE = "source_metadata_unavailable"
SHORT_ARTIST_SUFFIX_TEMPLATE = " [{artist}]"
SHORT_ARTIST_MAX_LENGTH = 60
VIDEO_MATCH_TOKEN_PATTERN = r"[^\W_]+"
VIDEO_MATCH_PARENS_PATTERN = r"\([^)]*\)|\[[^]]*\]"
VIDEO_MATCH_DASH_PATTERN = r"\s+[-–—]\s+"
VIDEO_MATCH_DEFAULT_ARTIST = ""

PLAYLIST_PAGE_SIZE = 50
PLAYLIST_UNKNOWN_ORDER_ERROR = "Playlist insertion deferred: source ordering metadata is missing"
PLAYLIST_RETRY_BATCH_SIZE = 5
PLAYLIST_RECOVERY_BATCH_SIZE = 1000
PLAYLIST_RETRY_OPTION = "--retry-playlists"
PLAYLIST_RETRY_HELP = "Retry playlist memberships and backfill recorded Shorts without downloading or uploading videos"
PLAYLIST_RETRY_REPORT = "Playlist recovery pass finished; unfinished assignments remain queued."
PLAYLIST_TYPE_SHORTS = "shorts"
SHORTS_PLAYLIST_TITLE = "shorts"
PLAYLIST_INVALID_RESPONSE_ERROR = "Playlist API response has no valid item list"
PLAYLIST_ORDER_DEFERRED_LOG = "Adding to playlist %s; existing ordering will be repaired separately"
PLAYLIST_METADATA_DEFERRED_LOG = "Adding to playlist %s while source ordering metadata is incomplete"
PLAYLIST_MANUAL_SORT_REQUIRED = "manualSortRequired"
PLAYLIST_QUOTA_ERRORS = frozenset(("quotaExceeded", "dailyLimitExceeded"))
PLAYLIST_UNSORTED_ERROR = "Playlist insertion deferred: existing order needs repair"

YOUTUBE_QUOTA_FILENAME = "youtube-quota.db"
YOUTUBE_QUOTA_TIMEZONE = "America/Los_Angeles"
YOUTUBE_QUOTA_NORMAL = 5500
YOUTUBE_QUOTA_REPAIR = 4000
YOUTUBE_QUOTA_GENERAL = YOUTUBE_QUOTA_NORMAL + YOUTUBE_QUOTA_REPAIR
YOUTUBE_QUOTA_MEMBERSHIP_LANE = "membership"
YOUTUBE_QUOTA_DEDICATED = 90
YOUTUBE_API_READ_COST = 1
YOUTUBE_API_WRITE_COST = 50
YOUTUBE_QUOTA_TIMEOUT = 30
YOUTUBE_QUOTA_ERROR = "Daily caller budget exhausted; reserved repair/upload quota remains protected"
PLAYLIST_REPAIR_MAX_MOVES = 75
PLAYLIST_VERIFY_DELAYS = (0, 1, 2, 4)
PLAYLIST_REPAIR_RETRY_SECONDS = 900

# Full-source repetition screening. Fixed resolution and bounded duration keep
# memory/CPU predictable; uninspectable sources are rejected, never truncated.
SHORT_STRUCTURE_FPS = 4.0
SHORT_STRUCTURE_WIDTH = 160
SHORT_STRUCTURE_HEIGHT = 90
SHORT_STRUCTURE_MAX_SECONDS = 600.0
SHORT_STRUCTURE_TIMEOUT_SECONDS = 600
SHORT_PROBE_TIMEOUT_SECONDS = 20
SHORT_STRUCTURE_DECODE_THREADS = 2
SHORT_LOOP_WIDTH = 32
SHORT_LOOP_HEIGHT = 18
SHORT_LOOP_MIN_SECONDS = 3.0
SHORT_LOOP_MIN_OVERLAP_SECONDS = 6.0
SHORT_LOOP_ALIGNMENT_FRAMES = 1
SHORT_LOOP_MATCH_CORRELATION = 0.85
SHORT_LOOP_MIN_COVERAGE = 0.35
SHORT_LOOP_WINDOWS = 4
SHORT_LOOP_MIN_WINDOW_COVERAGE = 0.15
SHORT_LOOP_MIN_PEAK_MARGIN = 0.20
SHORT_LOOP_EPSILON = 1e-6
SHORT_STRUCTURE_MIN_FRAMES = 2
SHORT_STRUCTURE_FRAME_TOLERANCE = 2
SHORT_MOTION_PEAK_MULTIPLIER = 1.5
SHORT_DEFAULT_SAMPLE_FPS = 0.5
SHORT_REJECT_TITLE_PATTERN = (
    r"\b(?:audio|visuali[sz]er|lyric(?:s|\s+video)?|trailer|teaser|snippet|"
    r"concert|live\s+(?:at|in|performance))\b"
)

# One shared upload cadence for instrumentals and Shorts, across model changes.
DEFAULT_UPLOAD_INTERVAL_SECONDS = 0.0
UPLOAD_INTERVAL_CONFIG_KEY = "upload_interval_seconds"
UPLOAD_INTERVAL_CONFIG_ERROR = "upload_interval_seconds must be a finite, nonnegative number"
UPLOAD_PACING_WAIT_LOG = "Upload pacing: waiting %.1f seconds before the next upload"
HISTORY_UPLOAD_TIMESTAMP_COLUMN = "uploaded_at"
HISTORY_LATEST_UPLOAD_QUERY = """
SELECT uploaded_at FROM (
    SELECT uploaded_at FROM uploads WHERE youtube_upload_id != ''
    UNION ALL
    SELECT short_uploaded_at AS uploaded_at FROM uploads
    WHERE youtube_short_upload_id != ''
)
ORDER BY julianday(uploaded_at) DESC LIMIT 1
"""
