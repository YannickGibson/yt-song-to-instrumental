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
SHORT_RETRYABLE_FAILURE = "short_failed"
PRIORITY_RETRYABLE_FAILURE = "priority_failed"
UPLOAD_KIND_SHORT = "short"
UPLOAD_KIND_INSTRUMENTAL = "instrumental"
RETRYABLE_PIPELINE_FAILURE_STATUSES = (
    SHORT_RETRYABLE_FAILURE, PRIORITY_RETRYABLE_FAILURE,
    "separation_failed", "render_failed", "upload_failed", "no_thumbnail",
)
RETRYABLE_PIPELINE_FAILURE_ERROR = "retryable track stages remain incomplete"
SHORT_SKIPPED_STATUSES = (
    "skipped_not_music_video",
    "skipped_disabled",
    "withdrawn_non_music_video",
    "withdrawn_source_mismatch",
    "deleted_owner_safety",
    "private_rejected_source",
)

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
SHORT_SOURCE_TITLE_QUOTA_LOG = "Source title unavailable until API budget resets; deferring Short"
SHORT_ARTIST_SUFFIX_TEMPLATE = " [{artist}]"
SHORT_ARTIST_MAX_LENGTH = 60
VIDEO_MATCH_TOKEN_PATTERN = r"[^\W_]+"
VIDEO_MATCH_PARENS_PATTERN = r"\([^)]*\)|\[[^]]*\]"
VIDEO_MATCH_DASH_PATTERN = r"\s+[-–—]\s+"
VIDEO_MATCH_DEFAULT_ARTIST = ""
VIDEO_MATCH_DURATION_TOLERANCE_SECONDS = 35.0
VIDEO_MATCH_DURATION_TOLERANCE_FRACTION = 0.35
VIDEO_CHANNEL_TAB = "/videos"
VIDEO_CHANNEL_TABS = ("/videos", "/releases", "/featured", "/shorts", "/streams")
VIDEO_CHANNEL_INDEX_ERROR_LOG = "Could not index trusted video channel %s: %s"
VIDEO_CHANNEL_MISSING_LOG = "No trusted video channel for %s; skipping Short source search"
VIDEO_CHANNEL_RESPONSE_ERROR = "Trusted channel index is unavailable"
VIDEO_CHANNEL_SCREENING_LOG = "Screening channel music video for %s: %s (%s)"
VIDEO_CHANNEL_PASSED_LOG = "Channel music video passed structural checks: %s"
VIDEO_CHANNEL_REJECTED_LOG = "Channel candidate failed structural checks: %s"
VIDEO_SOURCE_REJECTED_LOG = "Source for %s lacks trusted music-video evidence; checking its approved channel"
SHORT_MUSIC_VIDEO_LABEL = r"(?:official\s+(?:music\s+)?video|music\s+video|official\s+mv)"
SHORT_MUSIC_VIDEO_TITLE_PATTERN = (
    rf"(?:\(|\[)\s*{SHORT_MUSIC_VIDEO_LABEL}\s*(?:\)|\])"
    rf"|(?:^|\s){SHORT_MUSIC_VIDEO_LABEL}\s*$"
)

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
YOUTUBE_QUOTA_NORMAL_LANE = "normal"
YOUTUBE_QUOTA_REPAIR_LANE = "repair"
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
    r"concert|live\s+(?:at|in|performance)|game(?:play|s)?|gaming|gamer|"
    r"fps|fpv|shooter|battle\s+royale|walkthrough|playthrough|montage|"
    r"frag(?:movie|s)?|amv|gmv|anime|fan[\s-]*(?:made|edit|video)|unofficial|"
    r"reaction|reacting|review|cover|type\s+beat|remake|tutorial|how\s+to|"
    r"slowed|sped\s+up|nightcore|daycore|instrumental|karaoke|guitar|piano|"
    r"drum|behind\s+the\s+scenes|interview|podcast|mashup|"
    r"\d+\s*(?:hours?|hz)|8d\s+audio|bass\s+boosted)\b"
)

# One shared upload cadence for instrumentals and Shorts, across model changes.
DEFAULT_UPLOAD_INTERVAL_SECONDS = 0.0
DEFAULT_UPLOAD_INTERVAL_JITTER_SECONDS = 0.0
UPLOAD_INTERVAL_CONFIG_KEY = "upload_interval_seconds"
UPLOAD_INTERVAL_CONFIG_ERROR = "upload_interval_seconds must be a finite, nonnegative number"
UPLOAD_INTERVAL_JITTER_CONFIG_KEY = "upload_interval_jitter_seconds"
UPLOAD_INTERVAL_JITTER_CONFIG_ERROR = (
    "upload_interval_jitter_seconds must be finite, nonnegative, and no greater than upload_interval_seconds"
)
UPLOAD_INTERVAL_JITTER_SIGMA_BOUND = 3.0
UPLOAD_INTERVAL_JITTER_ROUND_DIGITS = 0
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

# Managed runtime defaults; private deployment paths are supplied in JSON.
RUNTIME_DEFAULTS = {
    "timezone": "UTC", "daily_time": [6, 5], "backup_time": [2, 55],
    "backup_retention": 7, "retry_seconds": 300, "retry_max_seconds": 3600,
    "rescan_seconds": 900, "poll_seconds": 60, "heartbeat_seconds": 2,
    "shutdown_seconds": 15, "max_log_bytes": 20971520,
}

PRIORITY_RETRYABLE_ERROR_PREFIX = "retryable: "

# Runtime protocol, service and upload journal constants.
RUNTIME_NUMBER_0 = 0
RUNTIME_MAIN = '__main__'
RUNTIME_PRIVATE_FILE_MODE = 384
RUNTIME_LOCK_OPEN_MODE = 'a+'
RUNTIME_BACKUPS = 'backups'
RUNTIME_BACKUP_DATE = 'backup_date'
RUNTIME_BACKUP_RETRY_AFTER = 'backup_retry_after'
RUNTIME_BACKUPS_COMPLETE = 'backups_complete'
RUNTIME_CONFIG = '--config'
RUNTIME_UMASK_VALUE = 63
RUNTIME_STATE_JSON = 'state.json'
RUNTIME_SUPERVISOR_STARTED = 'supervisor_started'
RUNTIME_PROJECT = 'project'
RUNTIME_ENVIRONMENT_ERROR = 'Worker environment must be separate from development .venv'
RUNTIME_TMP = '.tmp'
RUNTIME_TEXT_WRITE_MODE = 'w'
RUNTIME_NEWLINE = '\n'
RUNTIME_DATABASE_MISSING_ERROR = 'Production history database is missing'
RUNTIME_PRIVATE_DIRECTORY_MODE = 448
RUNTIME_BACKUP_DATABASES = 'backup_databases'
RUNTIME_PARTIAL = '.partial'
RUNTIME_CONSECUTIVE_FAILURES = 'consecutive_failures'
RUNTIME_RETRY_MAX_SECONDS = 'retry_max_seconds'
RUNTIME_TIMEZONE = 'timezone'
RUNTIME_RUNTIME_DIR = 'runtime_dir'
RUNTIME_SUPERVISOR_LOCK = 'supervisor.lock'
RUNTIME_SUPERVISOR_ALREADY_RUNNING = 'supervisor_already_running'
RUNTIME_SUPERVISOR_PID = 'supervisor_pid'
RUNTIME_JOB_RUNNING = 'job_running'
RUNTIME_WORKER_PID = 'worker_pid'
RUNTIME_RECOVERY_REQUIRED = 'recovery_required'
RUNTIME_PAUSE_FILE = 'pause_file'
RUNTIME_WORKER_LOCK = 'worker_lock'
RUNTIME_DATABASE = 'database'
RUNTIME_HEARTBEAT = 'heartbeat'
RUNTIME_PAUSED = 'paused'
RUNTIME_RESET_RETRIES = 'reset-retries'
RUNTIME_SUPERVISOR_STOPPED = 'supervisor_stopped'
RUNTIME_COMMAND = 'command'
RUNTIME_NUMBER_2 = 2
RUNTIME_NUMBER_1 = 1
RUNTIME_MODE_RO = '?mode=ro'
RUNTIME_NUMBER_15 = 15
RUNTIME_TIME = 'time'
RUNTIME_EVENT = 'event'
RUNTIME_BACKUP_TIME = 'backup_time'
RUNTIME_RETRY_SECONDS = 'retry_seconds'
RUNTIME_ATTEMPT_DAY = 'attempt_day'
RUNTIME_PENDING_REQUEST_COUNT = 'pending_request_count'
RUNTIME_POLL_SECONDS = 'poll_seconds'
RUNTIME_VENV = '.venv'
RUNTIME_PENDING_REQUESTS_QUERY = "SELECT id,status,requested_at FROM priority_requests WHERE status IN ('pending','processing') ORDER BY id"
RUNTIME_OK = 'ok'
RUNTIME_BACKUP_RETENTION = 'backup_retention'
RUNTIME_NUMBER_10 = 10
RUNTIME_RETRY_AFTER = 'retry_after'
RUNTIME_NUMBER_300 = 300
RUNTIME_BACKUP_FAILED = 'backup_failed'
RUNTIME_LAST_SUPERVISOR_ERROR = 'last_supervisor_error'
RUNTIME_SUPERVISOR_ITERATION_FAILED = 'supervisor_iteration_failed'
RUNTIME_BACKUP_INTEGRITY_CHECK_FAILED = 'Backup integrity check failed'
RUNTIME_DAILY_TIME = 'daily_time'
RUNTIME_RUN_NOW = 'run-now'
RUNTIME_YT_COMMENT_GATE = 'YT_COMMENT_GATE'
RUNTIME_YT_UPLOADER_REPO = 'YT_UPLOADER_REPO'
RUNTIME_PIPELINE_FINISHED = 'pipeline_finished'
RUNTIME_DAILY_SUCCESS_DATE = 'daily_success_date'
RUNTIME_WORKER_LOG = 'worker_log'
RUNTIME_JOB_STARTED = 'job_started'
RUNTIME_JOB_DUE_DATE = 'job_due_date'
RUNTIME_ENVIRONMENT = 'environment'
RUNTIME_LOG_OPEN_MODE = 'a'
RUNTIME_PIPELINE_STARTED = 'pipeline_started'
RUNTIME_JOB_FINISHED = 'job_finished'
RUNTIME_LAST_RETURNCODE = 'last_returncode'
RUNTIME_NEXT_RUN_AFTER = 'next_run_after'
RUNTIME_MAX_LOG_BYTES = 'max_log_bytes'
RUNTIME_WORKER_PREVIOUS_LOG = 'worker.previous.log'
RUNTIME_PRAGMA_QUICK_CHECK = 'PRAGMA quick_check'
RUNTIME_HEARTBEAT_SECONDS = 'heartbeat_seconds'
RUNTIME_RESCAN_SECONDS = 'rescan_seconds'
RUNTIME_SHUTDOWN_SECONDS = 'shutdown_seconds'
RUNTIME_LABEL = 'label'
RUNTIME_SYSTEM = 'system'
RUNTIME_PLIST_LABEL = 'Label'
RUNTIME_PROGRAMARGUMENTS = 'ProgramArguments'
RUNTIME_WORKINGDIRECTORY = 'WorkingDirectory'
RUNTIME_RUNATLOAD = 'RunAtLoad'
RUNTIME_KEEPALIVE = 'KeepAlive'
RUNTIME_THROTTLEINTERVAL = 'ThrottleInterval'
RUNTIME_EXITTIMEOUT = 'ExitTimeOut'
RUNTIME_UMASK = 'Umask'
RUNTIME_ENVIRONMENTVARIABLES = 'EnvironmentVariables'
RUNTIME_STANDARDOUTPATH = 'StandardOutPath'
RUNTIME_STANDARDERRORPATH = 'StandardErrorPath'
RUNTIME_STOP = 'stop'
RUNTIME_USERNAME = 'username'
RUNTIME_ACCOUNT_ERROR = 'Service requires a valid label and an ordinary user account'
RUNTIME_LIBRARY_LAUNCHDAEMONS = '/Library/LaunchDaemons'
RUNTIME_LIBRARY_LAUNCHAGENTS = 'Library/LaunchAgents'
RUNTIME_M = '-m'
RUNTIME_YT_SONG_TO_INSTRUMENTAL_RUNTIME = 'yt_song_to_instrumental.runtime'
RUNTIME_NUMBER_5 = 5
RUNTIME_PLIST_USERNAME = 'UserName'
RUNTIME_BIN_LAUNCHCTL = '/bin/launchctl'
RUNTIME_ADMIN_ERROR = 'System installation requires sudo; the worker runs as the configured user'
RUNTIME_ACTIVE_WORKER_ERROR = 'Worker is active. Admission is now paused; install again after the current run finishes'
RUNTIME_PLIST_TMP = '.plist.tmp'
RUNTIME_BOOTSTRAP = 'bootstrap'
RUNTIME_BOOTOUT = 'bootout'
RUNTIME_LABEL_PATTERN = '[A-Za-z0-9.-]+'
RUNTIME_SUPERVISOR_LOG = 'supervisor.log'
RUNTIME_SUPERVISOR_ERROR_LOG = 'supervisor-error.log'
RUNTIME_BINARY_WRITE_MODE = 'wb'
RUNTIME_DAEMON_FILE_MODE = 420
RUNTIME_HANDOFF_TIMEOUT_ERROR = 'Previous supervisor has not released its lock; admission remains paused'
RUNTIME_PRINT = 'print'
RUNTIME_PLIST_DISABLED = '.plist.disabled'
RUNTIME_INSTALL = 'install'
RUNTIME_RUN_REQUESTED = 'run_requested'
RUNTIME_SUPERVISOR = 'supervisor'
RUNTIME_WORKER = 'worker'
RUNTIME_ACTION = 'action'
RUNTIME_SYSTEM_2 = '--system'
RUNTIME_STORE_TRUE = 'store_true'
RUNTIME_SYSTEM_HELP = 'Manage a boot-time daemon running as the configured ordinary user'
RUNTIME_START = 'start'
RUNTIME_PAUSE = 'pause'
RUNTIME_STATUS = 'status'
RUNTIME_RESUME = 'resume'
UPLOAD_RECOVERY_UPLOAD_JOURNAL = 'upload_journal'
UPLOAD_RECOVERY_GET = 'GET'
UPLOAD_RECOVERY_UPLOADS = 'uploads'
UPLOAD_RECOVERY_SNIPPET = 'snippet'
UPLOAD_RECOVERY_NUMBER_1 = 1
UPLOAD_RECOVERY_EXPIRED = 'expired'
UPLOAD_RECOVERY_VISIBILITY_GRACE_SECONDS = 900
UPLOAD_RECOVERY_RESULT = 'result'
UPLOAD_RECOVERY_SESSION = 'session'
UPLOAD_RECOVERY_ID = 'id'
UPLOAD_RECOVERY_SCHEMA = 'CREATE TABLE IF NOT EXISTS upload_sessions (video_id TEXT, model TEXT, kind TEXT, payload TEXT NOT NULL, PRIMARY KEY(video_id, model, kind))'
UPLOAD_RECOVERY_SAVE_QUERY = 'INSERT OR REPLACE INTO upload_sessions VALUES (?, ?, ?, ?)'
UPLOAD_RECOVERY_RELATEDPLAYLISTS = 'relatedPlaylists'
UPLOAD_RECOVERY_BODY = 'body'
UPLOAD_RECOVERY_NEXTPAGETOKEN = 'nextPageToken'
UPLOAD_RECOVERY_AMBIGUOUS_ERROR = 'Ambiguous completed uploads require review; no new upload was started'
UPLOAD_RECOVERY_PENDING_ERROR = 'Expired upload session is awaiting external reconciliation'
UPLOAD_RECOVERY_RB = 'rb'
UPLOAD_RECOVERY_LOCATION = 'location'
UPLOAD_RECOVERY_PUT = 'PUT'
UPLOAD_RECOVERY_CONTENTDETAILS = 'contentDetails'
UPLOAD_RECOVERY_VIDEOID = 'videoId'
UPLOAD_RECOVERY_ITEMS = 'items'
UPLOAD_RECOVERY_HTTP_MISSING = 404
UPLOAD_RECOVERY_HTTP_GONE = 410
UPLOAD_RECOVERY_NUMBER_0 = 0
UPLOAD_RECOVERY_LOAD_QUERY = 'SELECT payload FROM upload_sessions WHERE video_id=? AND model=? AND kind=?'
UPLOAD_RECOVERY_HTTP_OK = 200
UPLOAD_RECOVERY_HTTP_CREATED = 201
UPLOAD_RECOVERY_HTTP_INCOMPLETE = 308
UPLOAD_RECOVERY_SHA256 = 'sha256'
UPLOAD_RECOVERY_CONTENT_RANGE = 'Content-Range'
UPLOAD_RECOVERY_CONTENT_LENGTH = 'content-length'
UPLOAD_RECOVERY_STATUS_RANGE = 'bytes */*'
UPLOAD_RECOVERY_EMPTY_CONTENT_LENGTH = '0'
UPLOAD_RECOVERY_DIGEST = 'digest'
UPLOAD_RECOVERY_PAGE_SIZE = 50
UPLOAD_RECOVERY_TITLE = 'title'
UPLOAD_RECOVERY_DESCRIPTION = 'description'
UPLOAD_RECOVERY_CLOCK_SKEW_SECONDS = 300
UPLOAD_RECOVERY_Z = 'Z'
UPLOAD_RECOVERY_UTC_OFFSET = '+00:00'
UPLOAD_RECOVERY_STARTED = 'started'
UPLOAD_RECOVERY_ID_SEPARATOR = ','
UPLOAD_RECOVERY_PUBLISHEDAT = 'publishedAt'

PRIORITY_REQUEUE_FAILED_QUERY = "UPDATE priority_requests SET status=?, started_at=NULL, finished_at=NULL WHERE status=? AND error LIKE ?"
PRIORITY_RETRYABLE_ERROR_PATTERN = PRIORITY_RETRYABLE_ERROR_PREFIX + "%"
UPLOAD_COMPLETED_LOG = "Upload complete: %s (ID: %s)"
STAGE_BINARY_READ_MODE = "rb"
MISSING_STAGE_OUTPUT_LOG = "Completed separation output is missing; regenerating source %s"

RUNTIME_DB_PATH = "DB_PATH"

# Source discovery and recent-release admission.
DEFAULT_RECENT_UPLOAD_WINDOW_DAYS = 30
RECENT_UPLOAD_WINDOW_KEY = "recent_upload_window_days"
RECENT_UPLOAD_WINDOW_ERROR = "recent_upload_window_days must be a nonnegative integer"
SOURCE_DATE_FORMAT = "%Y%m%d"
SOURCE_SCAN_WORKERS = 4
SOURCE_SCAN_POLL_SECONDS = 900
SOURCE_RETRY_SECONDS = 900
SOURCE_SCAN_START_LOG = "Refreshing all %d configured sources before queue admission"
SOURCE_SCAN_COMPLETE_LOG = "Source refresh complete: %d sources, %d new downloads, %d failed scans"
SOURCE_SCAN_FAILED_LOG = "Source refresh failed for %s: %s"
SOURCE_SCAN_EMPTY_ERROR = "Source enumeration returned no response"
SOURCE_ENTRY_ID = "id"
SOURCE_FIRST_INDEX = 0
SOURCE_EMPTY_COUNT = 0
SOURCE_DEFERRED_LOG = "Queue refreshed; deferring source %s to admit higher-priority work"
RECENT_UPLOAD_LOG = "Recent release %s: uploading without backlog pacing"
SOURCE_MEMBERSHIP_SCHEMA = """
CREATE TABLE IF NOT EXISTS source_memberships (
    video_id TEXT NOT NULL, source_url TEXT NOT NULL, tab TEXT NOT NULL,
    PRIMARY KEY(video_id, source_url, tab)
);
"""
SOURCE_MEMBERSHIP_SAVE_QUERY = "INSERT OR IGNORE INTO source_memberships VALUES (?, ?, ?)"
SOURCE_MEMBERSHIP_LOAD_QUERY = "SELECT source_url, tab FROM source_memberships WHERE video_id=?"
SOURCE_PENDING_PRIORITY_QUERY = "SELECT 1 FROM priority_requests WHERE status=? LIMIT 1"
SOURCE_DEFAULT_TAB = "videos"

SOURCE_SINGLE_QUEUE_COUNT = 1
