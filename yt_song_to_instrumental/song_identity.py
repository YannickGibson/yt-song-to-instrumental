import unicodedata

from yt_song_to_instrumental.constants import (
    SONG_IDENTITY_UNICODE_FORM, SONG_IDENTITY_EDGE_PUNCTUATION,
)


def normalize_song_identity(value: str) -> str:
    """Ignore cosmetic edge punctuation, never remove version qualifiers."""
    return unicodedata.normalize(SONG_IDENTITY_UNICODE_FORM, value).casefold().strip(
        SONG_IDENTITY_EDGE_PUNCTUATION
    ).strip()
