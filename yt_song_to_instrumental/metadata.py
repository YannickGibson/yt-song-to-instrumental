import re

from yt_song_to_instrumental.config import ArtistAliasResolver
from yt_song_to_instrumental.constants import (
    ALL_TEMPLATE_TAGS,
    TAG_ALBUM_NAME,
    TAG_ARTIST_NAME,
    TAG_ARTIST_TAG,
    TAG_CHANNEL_URL,
    TAG_LABEL_NAME,
    TAG_MODEL_NAME,
    TAG_ORIGINAL_CHANNEL_URL,
    TAG_ORIGINAL_URL,
    TAG_TRACK_TITLE,
    TAG_VIDEO_TITLE,
    TEMPLATE_TAG_PATTERN,
    TITLE_PARENTHETICAL_PATTERN,
    YOUTUBE_TITLE_MAX_LENGTH,
)

_TITLE_PARENS_RE = re.compile(TITLE_PARENTHETICAL_PATTERN)
_TEMPLATE_TAG_RE = re.compile(TEMPLATE_TAG_PATTERN)
# Strips ALL parenthetical segments, including (feat. X) ones. Used inside
# render_video_title once features have been harvested from the title.
_ALL_PARENS_RE = re.compile(r"\s*\([^)]*\)\s*")
_FEAT_TITLE_RE = re.compile(r"\(\s*(?:feat\.?|ft\.?)\s*(.+?)\s*\)", re.IGNORECASE)
# Matches an un-parenthesized trailing feature credit: "Song ft. X & Y" or
# "Song feat. X". The base title is group(1), the features blob is group(2).
_UNPAREN_FEAT_RE = re.compile(r"^(.+?)\s+(?:ft|feat)\.?\s+(.+)$", re.IGNORECASE)
_ARTIST_SPLIT_PATTERN = re.compile(r"\s*(?:,|&|/|\bfeat\.?\s|\bft\.?\s|\bx\b)\s*", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")


def strip_title_parentheticals(text: str) -> str:
    return _TITLE_PARENS_RE.sub(" ", text).strip()


def _strip_all_parens(text: str) -> str:
    return _ALL_PARENS_RE.sub(" ", text).strip()


def _extract_features_from_title(title: str) -> list[str]:
    m = _FEAT_TITLE_RE.search(title)
    if not m:
        return []
    return [p.strip() for p in _ARTIST_SPLIT_PATTERN.split(m.group(1)) if p.strip()]


def _split_unparenthesized_features(title: str) -> tuple[str, list[str]]:
    """Returns (base_title, [feature_names]) by matching trailing
    'Song ft. X & Y' / 'Song feat. X' patterns. If no match, returns
    (title, [])."""
    m = _UNPAREN_FEAT_RE.match(title)
    if not m:
        return title, []
    base = m.group(1).strip()
    rest = m.group(2)
    artists = [p.strip() for p in _ARTIST_SPLIT_PATTERN.split(rest) if p.strip()]
    return base, artists


def _collapse_whitespace(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def _prefer_canonical_over_handles(text: str, aliases: ArtistAliasResolver) -> str:
    """Within an already-credit-style title, replace @-prefixed alias variants
    with their canonical name when the alias group has a non-@ canonical.
    Leaves bare canonical names and @-only artist groups untouched.
    """
    for canonical, variants in aliases.iter_groups():
        if canonical.startswith("@"):
            continue
        for variant in variants:
            if variant == canonical or not variant.startswith("@"):
                continue
            text = re.sub(re.escape(variant), canonical, text, flags=re.IGNORECASE)
    return text


# Audio rips have no abrupt video pauses, so they're preferred over Music
# Video uploads when the same track exists under both. Lower value = better.
_AUDIO_MARKERS_RE = re.compile(r"\(\s*(?:official\s+)?audio\s*\)", re.IGNORECASE)
_VIDEO_MARKERS_RE = re.compile(r"\(\s*(?:official\s+)?(?:music\s+)?video\s*\)", re.IGNORECASE)


def version_priority(raw_title: str) -> int:
    if _AUDIO_MARKERS_RE.search(raw_title):
        return 0
    if _VIDEO_MARKERS_RE.search(raw_title):
        return 2
    return 1


def _sanitize_for_hashtag(text: str) -> str:
    parts = _ARTIST_SPLIT_PATTERN.split(text)
    tags = []
    for part in parts:
        cleaned = re.sub(r"[^a-zA-Z0-9]", "", part).lower()
        if cleaned:
            tags.append(f"#{cleaned}")
    return " ".join(tags)


def _sanitize_text(text: str) -> str:
    text = text.replace("<", "").replace(">", "")
    return text.strip()


def validate_template_tags(template: str, template_name: str) -> None:
    """Raise ValueError if `template` contains any <kebab-case> tag that is not
    in ALL_TEMPLATE_TAGS. Prevents unsupported tags from silently rendering as
    literal angle-bracketed strings in public YouTube uploads."""
    found = set(_TEMPLATE_TAG_RE.findall(template))
    unsupported = sorted(found - set(ALL_TEMPLATE_TAGS))
    if unsupported:
        supported = ", ".join(ALL_TEMPLATE_TAGS)
        raise ValueError(
            f"Unsupported template tag(s) in {template_name}: {', '.join(unsupported)}. "
            f"Supported tags: {supported}"
        )


def render_template(
    template: str,
    artist_name: str = "",
    track_title: str = "",
    album_name: str = "",
    original_url: str = "",
    original_channel_url: str = "",
    model_name: str = "",
    label_name: str = "",
    channel_url: str = "",
    video_title: str = "",
) -> str:
    replacements = {
        TAG_ARTIST_NAME: _sanitize_text(artist_name),
        TAG_TRACK_TITLE: _sanitize_text(track_title),
        TAG_ALBUM_NAME: _sanitize_text(album_name),
        TAG_ORIGINAL_URL: original_url,
        TAG_ORIGINAL_CHANNEL_URL: original_channel_url,
        TAG_MODEL_NAME: model_name,
        TAG_LABEL_NAME: _sanitize_text(label_name),
        TAG_ARTIST_TAG: _sanitize_for_hashtag(artist_name),
        TAG_CHANNEL_URL: channel_url,
        TAG_VIDEO_TITLE: _sanitize_text(video_title),
    }

    result = template
    for tag, value in replacements.items():
        result = result.replace(tag, value)

    return result


def render_title(
    template: str,
    artist_name: str = "",
    track_title: str = "",
    album_name: str = "",
    model_name: str = "",
    label_name: str = "",
) -> str:
    title = render_template(
        template,
        artist_name=artist_name,
        track_title=track_title,
        album_name=album_name,
        model_name=model_name,
        label_name=label_name,
    )
    if len(title) > YOUTUBE_TITLE_MAX_LENGTH:
        title = title[:YOUTUBE_TITLE_MAX_LENGTH - 3] + "..."
    return title


def render_description(
    template: str,
    artist_name: str = "",
    track_title: str = "",
    album_name: str = "",
    original_url: str = "",
    original_channel_url: str = "",
    model_name: str = "",
    label_name: str = "",
    channel_url: str = "",
    video_title: str = "",
) -> str:
    return render_template(
        template,
        artist_name=artist_name,
        track_title=track_title,
        album_name=album_name,
        original_url=original_url,
        original_channel_url=original_channel_url,
        model_name=model_name,
        label_name=label_name,
        channel_url=channel_url,
        video_title=video_title,
    )


def render_playlist_name(
    template: str,
    artist_name: str = "",
    album_name: str = "",
    label_name: str = "",
) -> str:
    return render_template(
        template,
        artist_name=artist_name,
        album_name=album_name,
        label_name=label_name,
    )


def _split_title_on_dash(title: str) -> tuple[str, str] | None:
    parts = title.split(" - ", 1)
    if len(parts) != 2:
        return None
    return parts[0], parts[1]


def _matches_primary_alone(lhs: str, primary_variants: list[str]) -> bool:
    variants = {v.strip().lower() for v in primary_variants}
    return lhs.strip().lower() in variants


def _is_multi_artist_credit(lhs: str, primary_variants: list[str]) -> bool:
    parts = [p.strip() for p in _ARTIST_SPLIT_PATTERN.split(lhs) if p.strip()]
    if len(parts) < 2:
        return False
    variants = {v.strip().lower() for v in primary_variants}
    return any(p.lower() in variants for p in parts)


def _truncate(title: str) -> str:
    if len(title) > YOUTUBE_TITLE_MAX_LENGTH:
        return title[:YOUTUBE_TITLE_MAX_LENGTH - 3] + "..."
    return title


def render_video_title(
    template: str,
    primary_artist: str,
    raw_title: str,
    all_artists: list[str],
    album_name: str,
    model_name: str,
    label_name: str,
    aliases: ArtistAliasResolver,
) -> str:
    primary_variants = aliases.variants_of(primary_artist)
    primary_lower = primary_artist.strip().lower()

    # Case A: verbatim multi-artist credit. Preserve the title's structure,
    # but swap @-handle variants for their canonical names when the alias
    # group provides one (e.g. "@coldmary" → "Cold Mary").
    split = _split_title_on_dash(raw_title)
    if split is not None and _is_multi_artist_credit(split[0], primary_variants):
        normalized = _prefer_canonical_over_handles(raw_title, aliases)
        return _truncate(_collapse_whitespace(f"{normalized} (Instrumental)"))

    # For Cases B/C we strip ALL parens (feat. info already harvested into the
    # raw_features list below) and any trailing un-parenthesized "ft. X" credit.
    parenthesized_features = _extract_features_from_title(raw_title)
    cleaned_title = _strip_all_parens(raw_title) or raw_title
    cleaned_title, unparen_features = _split_unparenthesized_features(cleaned_title)

    # Canonicalize + dedup all feature sources, preserving order: YTMusic first,
    # then parenthesized title feats, then un-parenthesized.
    seen = {primary_lower}
    features: list[str] = []
    for a in list(all_artists) + parenthesized_features + unparen_features:
        canon = aliases.resolve(a)
        key = canon.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        features.append(canon)

    effective_title = cleaned_title
    split = _split_title_on_dash(cleaned_title)
    if split is not None and _matches_primary_alone(split[0], primary_variants):
        effective_title = split[1].strip()

    track = effective_title
    if features:
        track = f"{track} (feat. {' & '.join(features)})"

    return render_title(
        template,
        artist_name=primary_artist,
        track_title=_collapse_whitespace(track),
        album_name=album_name,
        model_name=model_name,
        label_name=label_name,
    )
