from yt_song_to_instrumental.constants import (
    AVAILABLE_MODELS,
    MODEL_DEMUCS,
    MODEL_INST_HQ_4,
    MODEL_MEL_GABOX,
)
from yt_song_to_instrumental.separator.base import SeparatorBackend


def get_separator(model_name: str) -> SeparatorBackend:
    if model_name == MODEL_DEMUCS:
        from yt_song_to_instrumental.separator.demucs_backend import DemucsBackend
        return DemucsBackend()
    elif model_name == MODEL_INST_HQ_4:
        from yt_song_to_instrumental.separator.inst_hq_4_backend import InstHQ4Backend
        return InstHQ4Backend()
    elif model_name == MODEL_MEL_GABOX:
        from yt_song_to_instrumental.separator.mel_gabox_backend import MelGaboxBackend
        return MelGaboxBackend()
    raise ValueError(f"Unknown model: {model_name}. Available: {AVAILABLE_MODELS}")
