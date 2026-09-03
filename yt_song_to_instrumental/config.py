import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

from yt_song_to_instrumental.constants import (
    AFTER_DATE_PATTERN,
    AVAILABLE_MODELS,
    DEFAULT_MODEL,
    DEFAULT_PRIVACY_STATUS,
    LABEL_CONFIG_FILENAME,
    DEFAULT_TRIM_SILENCE,
    DEFAULT_TRIM_THRESHOLD_DB,
)

_AFTER_DATE_RE = re.compile(AFTER_DATE_PATTERN)

load_dotenv()


class YouTubeConfig(BaseSettings):
    client_secrets_file: str = Field(alias="YOUTUBE_CLIENT_SECRETS_FILE")
    token_file: str = Field(default="token.json", alias="YOUTUBE_TOKEN_FILE")
    channel_id: str = Field(alias="YOUTUBE_CHANNEL_ID")

    model_config = {"env_prefix": "", "extra": "ignore", "populate_by_name": True}


class AppConfig(BaseSettings):
    separator_model: str = Field(default=DEFAULT_MODEL, alias="SEPARATOR_MODEL")
    output_dir: str = Field(default="output", alias="OUTPUT_DIR")
    tmp_dir: str = Field(default="tmp", alias="TMP_DIR")
    db_path: str = Field(default="data/history.db", alias="DB_PATH")
    default_privacy: str = Field(default=DEFAULT_PRIVACY_STATUS, alias="DEFAULT_PRIVACY")

    model_config = {"env_prefix": "", "extra": "ignore", "populate_by_name": True}


@dataclass(frozen=True)
class Source:
    url: str
    after_date: str | None
    preserve_original_video_title: bool = False
    tab: str = "videos"
    create_album_playlists: bool = True
    video_channel_url: str | None = None


def _parse_source(raw: dict, default_tab: str = "videos") -> Source:
    url = raw["url"]
    if not isinstance(url, str) or not url.strip():
        raise ValueError(f"source url must be a non-empty string, got {url!r}")
    after_date = raw["after_date"]
    if after_date is not None:
        if not isinstance(after_date, str) or not _AFTER_DATE_RE.match(after_date):
            raise ValueError(
                f"source after_date must be YYYYMMDD or null, got {after_date!r} for url {url!r}"
            )
    raw_val = raw.get("preserve_original_video_title")
    if raw_val is None:
        raw_val = raw.get("is_uploader")
    preserve_original_video_title = bool(raw_val) if raw_val is not None else False
    raw_tab = raw.get("tab")
    if raw_tab is None:
        tab = default_tab
    elif not isinstance(raw_tab, str) or raw_tab.strip().lower() not in ("videos", "releases"):
        raise ValueError(f"source tab must be 'videos' or 'releases', got {raw_tab!r} for url {url!r}")
    else:
        tab = raw_tab.strip().lower()

    raw_create_album_pl = raw.get("create_album_playlists")
    create_album_playlists = bool(raw_create_album_pl) if raw_create_album_pl is not None else True

    raw_video_channel_url = raw.get("video_channel_url")
    if raw_video_channel_url is not None:
        if not isinstance(raw_video_channel_url, str) or not raw_video_channel_url.strip():
            raise ValueError(
                f"source video_channel_url must be a non-empty string or null, got {raw_video_channel_url!r} for url {url!r}"
            )
        video_channel_url = raw_video_channel_url.strip()
    else:
        video_channel_url = None

    return Source(
        url=url,
        after_date=after_date,
        preserve_original_video_title=preserve_original_video_title,
        tab=tab,
        create_album_playlists=create_album_playlists,
        video_channel_url=video_channel_url,
    )




class ArtistAliasResolver:
    def __init__(self, groups: list[list[str]]):
        from yt_song_to_instrumental.metadata import strip_topic_suffix

        self._lookup: dict[str, str] = {}
        self._variants: dict[str, list[str]] = {}
        for group in groups:
            # A group of one is valid: it registers an artist as "known" (so
            # they get a playlist) without declaring any alias variants.
            if not group:
                continue
            canonical = strip_topic_suffix(group[0])
            clean_group = [strip_topic_suffix(n) for n in group if n]
            self._variants[canonical.strip().lower()] = clean_group
            for name in group:
                clean_name = strip_topic_suffix(name)
                self._lookup[clean_name.strip().lower()] = canonical
                self._lookup[name.strip().lower()] = canonical

    def resolve(self, name: str) -> str:
        from yt_song_to_instrumental.metadata import strip_topic_suffix

        clean_name = strip_topic_suffix(name)
        if clean_name.strip().lower() in self._lookup:
            return self._lookup[clean_name.strip().lower()]
        if name.strip().lower() in self._lookup:
            return self._lookup[name.strip().lower()]
        return clean_name

    def variants_of(self, canonical: str) -> list[str]:
        from yt_song_to_instrumental.metadata import strip_topic_suffix

        clean_canonical = strip_topic_suffix(canonical)
        variants = self._variants.get(clean_canonical.strip().lower(), [canonical, clean_canonical])
        res = []
        for v in variants:
            c = strip_topic_suffix(v)
            if c and c not in res:
                res.append(c)
            if v and v not in res:
                res.append(v)
        return res

    def is_known(self, name: str) -> bool:
        """True if `name` (canonical or any variant) appears in the configured
        artist_aliases. Used to gate which collaborators get their own
        playlist."""
        from yt_song_to_instrumental.metadata import strip_topic_suffix

        clean_name = strip_topic_suffix(name)
        return clean_name.strip().lower() in self._lookup or name.strip().lower() in self._lookup

    def iter_groups(self):
        """Yield (canonical, all_variants) for each alias group. Used by the
        title renderer to swap @-prefixed variants for the canonical name."""
        for variants in self._variants.values():
            yield variants[0], variants



class LabelConfig:
    def __init__(self, data: dict):
        # Imported here to avoid a circular import: metadata.py imports
        # ArtistAliasResolver from this module.
        from yt_song_to_instrumental.metadata import validate_template_tags

        self.channel_name: str = data["channel"]["name"]
        self.channel_description: str = data["channel"]["description"]
        self.channel_url: str = data["channel"].get("url", "")
        self.label_name: str = data["label"]["name"]
        self.video_title_template: str = data["templates"]["video_title"]
        self.video_description_template: str = data["templates"]["video_description"]
        self.album_playlist_name_template: str = data["templates"]["album_playlist_name"]
        self.artist_playlist_name_template: str = data["templates"]["artist_playlist_name"]
        # The label-channel "all uploads" playlist name. Defaulted for
        # backwards-compatibility with label.yml files that predate the feature.
        self.channel_playlist_name_template: str = data["templates"].get(
            "channel_playlist_name", "<channel-name> Uploaded Instrumentals",
        )
        validate_template_tags(self.video_title_template, "templates.video_title")
        validate_template_tags(self.video_description_template, "templates.video_description")
        validate_template_tags(self.album_playlist_name_template, "templates.album_playlist_name")
        validate_template_tags(self.artist_playlist_name_template, "templates.artist_playlist_name")
        validate_template_tags(self.channel_playlist_name_template, "templates.channel_playlist_name")
        self.artist_aliases: ArtistAliasResolver = ArtistAliasResolver(
            data.get("artist_aliases", []),
        )
        self.create_playlists_for_collaborators: bool = data["create_playlists_for_collaborators"]
        raw_tab = data.get("tab", "videos")
        if not isinstance(raw_tab, str) or raw_tab.strip().lower() not in ("videos", "releases"):
            raise ValueError(f"label tab must be 'videos' or 'releases', got {raw_tab!r}")
        self.tab: str = raw_tab.strip().lower()
        self.sources: list[Source] = [_parse_source(s, default_tab=self.tab) for s in data["sources"]]
        # Optional. Lets a label pin the separation backend without setting
        # --model on every invocation. CLI --model still wins if provided.
        raw_default_model = data.get("default_model")
        self.default_model: str = raw_default_model if raw_default_model else DEFAULT_MODEL
        if self.default_model not in AVAILABLE_MODELS:
            raise ValueError(
                f"default_model={self.default_model!r} is not a known model "
                f"(available: {AVAILABLE_MODELS})"
            )
        raw_trim_silence = data.get("trim_silence")
        self.trim_silence: bool = raw_trim_silence if raw_trim_silence is not None else DEFAULT_TRIM_SILENCE
        raw_trim_threshold_db = data.get("trim_silence_threshold_db")
        self.trim_silence_threshold_db: float = raw_trim_threshold_db if raw_trim_threshold_db is not None else DEFAULT_TRIM_THRESHOLD_DB

        # Optional YouTube Shorts upload configuration
        self.upload_short: bool = bool(data.get("upload_short", False))
        self.upload_short_if_music_video: bool = bool(data.get("upload_short_if_music_video", False))
        if self.upload_short and self.upload_short_if_music_video:
            raise ValueError(
                "Invalid configuration: both 'upload_short' and 'upload_short_if_music_video' "
                "cannot be true simultaneously."
            )

        default_short_desc = f"Full instrumental: <full-video-url>\n\n{self.video_description_template}"
        self.short_description_template: str = data.get("templates", {}).get(
            "short_description", default_short_desc
        )
        validate_template_tags(self.short_description_template, "templates.short_description")



def load_label_config(config_path: Path | None = None) -> LabelConfig:
    path = config_path or Path(LABEL_CONFIG_FILENAME)
    with open(path) as f:
        data = yaml.safe_load(f)
    return LabelConfig(data)
