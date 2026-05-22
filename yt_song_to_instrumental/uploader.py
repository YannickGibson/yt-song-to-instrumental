import logging
import time
from pathlib import Path

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from yt_song_to_instrumental.constants import (
    RETRYABLE_UPLOAD_REASONS,
    UPLOAD_CHUNK_SIZE_BYTES,
    UPLOAD_RETRY_BACKOFF_MULTIPLIER,
    UPLOAD_RETRY_INITIAL_WAIT_SECONDS,
    UPLOAD_RETRY_MAX_WAIT_SECONDS,
    YOUTUBE_CATEGORY_MUSIC,
    YOUTUBE_SCOPE,
    YOUTUBE_UPLOAD_SCOPE,
)

logger = logging.getLogger(__name__)

SCOPES = [YOUTUBE_UPLOAD_SCOPE, YOUTUBE_SCOPE]


def authenticate(client_secrets_file: str, token_file: str) -> Resource:
    creds = None

    token_path = Path(token_file)
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(client_secrets_file, SCOPES)
            creds = flow.run_local_server(
                port=8080,
                open_browser=False,
            )
            logger.info("If no browser opened, visit the URL printed above to authorize.")

        with open(token_file, "w") as f:
            f.write(creds.to_json())

    return build("youtube", "v3", credentials=creds)


def _extract_error_reason(err: HttpError) -> str:
    """Extract the first 'reason' field from an HttpError's details, e.g.
    'uploadLimitExceeded' for the per-account rate-limit rejection."""
    try:
        for detail in (err.error_details or []):
            reason = detail.get("reason") if isinstance(detail, dict) else None
            if reason:
                return reason
    except Exception:
        pass
    return ""


def _retry_wait_for(attempt: int) -> float:
    """Exponential backoff in seconds, capped at UPLOAD_RETRY_MAX_WAIT_SECONDS."""
    wait = UPLOAD_RETRY_INITIAL_WAIT_SECONDS * (UPLOAD_RETRY_BACKOFF_MULTIPLIER ** (attempt - 1))
    return min(wait, UPLOAD_RETRY_MAX_WAIT_SECONDS)


def _do_single_upload_attempt(service, body: dict, file_path: Path, title: str) -> str:
    media = MediaFileUpload(
        str(file_path),
        chunksize=UPLOAD_CHUNK_SIZE_BYTES,
        resumable=True,
    )
    request = service.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            logger.info("Upload progress: %d%%", int(status.progress() * 100))
    video_id = response["id"]
    logger.info("Upload complete: %s (ID: %s)", title, video_id)
    return video_id


def upload_video(
    service,
    file_path: Path,
    title: str,
    description: str,
    privacy: str,
    category: str = YOUTUBE_CATEGORY_MUSIC,
    max_total_wait_seconds: float | None = None,
    _sleep=time.sleep,
) -> str:
    """Upload a video, retrying with exponential backoff on YouTube's per-account
    rate-limit errors (`uploadLimitExceeded` / `rateLimitExceeded`). Other errors
    propagate.

    `max_total_wait_seconds` caps cumulative sleep across retries for THIS
    upload; None = no cap, retry indefinitely.
    """
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "categoryId": category,
        },
        "status": {
            "privacyStatus": privacy,
        },
    }

    attempt = 0
    total_waited = 0.0
    while True:
        attempt += 1
        logger.info("Uploading: %s (attempt %d)", title, attempt)
        try:
            return _do_single_upload_attempt(service, body, file_path, title)
        except HttpError as e:
            reason = _extract_error_reason(e)
            if reason not in RETRYABLE_UPLOAD_REASONS:
                raise
            wait_seconds = _retry_wait_for(attempt)
            if max_total_wait_seconds is not None and total_waited + wait_seconds > max_total_wait_seconds:
                logger.error(
                    "Giving up on %s after waiting %.1f min total (cap %.1f min); reason=%s",
                    title, total_waited / 60, max_total_wait_seconds / 60, reason,
                )
                raise
            logger.warning(
                "Rate-limited on %s (reason=%s, attempt %d). Sleeping %.0f min before retry.",
                title, reason, attempt, wait_seconds / 60,
            )
            _sleep(wait_seconds)
            total_waited += wait_seconds


def list_channel_videos(service, channel_id: str, max_results: int = 500) -> set[str]:
    titles: set[str] = set()
    page_token = None

    while True:
        response = service.search().list(
            part="snippet",
            channelId=channel_id,
            maxResults=min(max_results - len(titles), 50),
            type="video",
            pageToken=page_token,
        ).execute()

        for item in response.get("items", []):
            titles.add(item["snippet"]["title"])

        page_token = response.get("nextPageToken")
        if not page_token or len(titles) >= max_results:
            break

    return titles


def add_video_to_playlist(service, playlist_id: str, video_id: str) -> None:
    body = {
        "snippet": {
            "playlistId": playlist_id,
            "resourceId": {
                "kind": "youtube#video",
                "videoId": video_id,
            },
        },
    }
    service.playlistItems().insert(part="snippet", body=body).execute()
    logger.info("Added video %s to playlist %s", video_id, playlist_id)
