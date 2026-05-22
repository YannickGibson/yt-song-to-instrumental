from yt_song_to_instrumental.constants import (
    AVAILABLE_MODELS,
    MODEL_DEMUCS,
    MODEL_MDXNET,
)
from yt_song_to_instrumental.separator.base import SeparatorBackend


def get_separator(model_name: str) -> SeparatorBackend:
    if model_name == MODEL_DEMUCS:
        from yt_song_to_instrumental.separator.demucs_backend import DemucsBackend
        return DemucsBackend()
    elif model_name == MODEL_MDXNET:
        from yt_song_to_instrumental.separator.mdxnet_backend import MDXNetBackend
        return MDXNetBackend()
    raise ValueError(f"Unknown model: {model_name}. Available: {AVAILABLE_MODELS}")
