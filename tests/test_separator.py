import pytest

from yt_song_to_instrumental.separator import get_separator
from yt_song_to_instrumental.separator.base import SeparatorBackend
from yt_song_to_instrumental.separator.demucs_backend import DemucsBackend
from yt_song_to_instrumental.separator.mdxnet_backend import MDXNetBackend


class TestGetSeparator:
    def test_returns_demucs_backend(self):
        backend = get_separator("htdemucs")
        assert isinstance(backend, DemucsBackend)
        assert isinstance(backend, SeparatorBackend)

    def test_returns_mdxnet_backend(self):
        backend = get_separator("mdxnet")
        assert isinstance(backend, MDXNetBackend)
        assert isinstance(backend, SeparatorBackend)

    def test_raises_on_unknown_model(self):
        with pytest.raises(ValueError, match="Unknown model"):
            get_separator("nonexistent_model")


class TestDemucsBackend:
    def test_name(self):
        backend = DemucsBackend()
        assert backend.name() == "HTDemucs"

    def test_gpu_not_required(self):
        backend = DemucsBackend()
        assert backend.gpu_required() is False

    def test_min_memory(self):
        backend = DemucsBackend()
        assert backend.min_memory_gb() == 4.0


class TestMDXNetBackend:
    def test_name(self):
        backend = MDXNetBackend()
        assert backend.name() == "MDX-Net"

    def test_gpu_not_required(self):
        backend = MDXNetBackend()
        assert backend.gpu_required() is False

    def test_min_memory(self):
        backend = MDXNetBackend()
        assert backend.min_memory_gb() == 2.0
