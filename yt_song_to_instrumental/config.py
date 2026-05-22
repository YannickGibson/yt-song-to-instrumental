import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

from yt_song_to_instrumental.constants import (
    AFTER_DATE_PATTERN,
    DEFAULT_MODEL,
    DEFAULT_PRIVACY_STATUS,
    LABEL_CONFIG_FILENAME,
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


def _parse_source(raw: dict) -> Source:
    url = raw["url"]
    if not isinstance(url, str) or not url.strip():
        raise ValueError(f"source url must be a non-empty string, got {url!r}")
    after_date = raw["after_date"]
    if after_date is not None:
        if not isinstance(after_date, str) or not _AFTER_DATE_RE.match(after_date):
            raise ValueError(
                f"source after_date must be YYYYMMDD or null, got {after_date!r} for url {url!r}"
            )
    return Source(url=url, after_date=after_date)


class ArtistAliasResolver:
    def __init__(self, groups: list[list[str]]):
        self._lookup: dict[str, str] = {}
        self._variants: dict[str, list[str]] = {}
        for group in groups:
            # A group of one is valid: it registers an artist as "known" (so
            # they get a playlist) without declaring any alias variants.
            if not group:
                continue
            canonical = group[0]
            self._variants[canonical.strip().lower()] = list(group)
            for name in group:
                self._lookup[name.strip().lower()] = canonical

    def resolve(self, name: str) -> str:
        return self._lookup.get(name.strip().lower(), name)

    def variants_of(self, canonical: str) -> list[str]:
        return self._variants.get(canonical.strip().lower(), [canonical])

    def is_known(self, name: str) -> bool:
        """True if `name` (canonical or any variant) appears in the configured
        artist_aliases. Used to gate which collaborators get their own
        playlist."""
        return name.strip().lower() in self._lookup

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
        validate_template_tags(self.video_title_template, "templates.video_title")
        validate_template_tags(self.video_description_template, "templates.video_description")
        validate_template_tags(self.album_playlist_name_template, "templates.album_playlist_name")
        validate_template_tags(self.artist_playlist_name_template, "templates.artist_playlist_name")
        self.artist_aliases: ArtistAliasResolver = ArtistAliasResolver(
            data.get("artist_aliases", []),
        )
        self.create_playlists_for_collaborators: bool = data["create_playlists_for_collaborators"]
        self.sources: list[Source] = [_parse_source(s) for s in data["sources"]]


def load_label_config(config_path: Path | None = None) -> LabelConfig:
    path = config_path or Path(LABEL_CONFIG_FILENAME)
    with open(path) as f:
        data = yaml.safe_load(f)
    return LabelConfig(data)
