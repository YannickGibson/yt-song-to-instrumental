from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from yt_song_to_instrumental.separator import get_separator
from yt_song_to_instrumental.separator.base import SeparatorBackend
from yt_song_to_instrumental.separator.demucs_backend import DemucsBackend
from yt_song_to_instrumental.separator.inst_hq_4_backend import InstHQ4Backend


class TestGetSeparator:
    def test_returns_demucs_backend(self):
        backend = get_separator("htdemucs")
        assert isinstance(backend, DemucsBackend)
        assert isinstance(backend, SeparatorBackend)

    def test_returns_inst_hq_4_backend(self):
        backend = get_separator("inst_hq_4")
        assert isinstance(backend, InstHQ4Backend)
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


class TestInstHQ4Backend:
    def test_name(self):
        backend = InstHQ4Backend()
        assert backend.name() == "UVR-MDX-NET Inst_HQ_4"

    def test_gpu_not_required(self):
        backend = InstHQ4Backend()
        assert backend.gpu_required() is False

    def test_min_memory(self):
        backend = InstHQ4Backend()
        assert backend.min_memory_gb() == 3.0

    def test_separate_moves_audio_separator_outputs_to_canonical_layout(self, tmp_path):
        """audio-separator names outputs `<stem>_(Instrumental)_<model>.wav`;
        the backend must rename/move them to `<output>/inst_hq_4/<stem>/{no_vocals,vocals}.wav`
        so the rest of the pipeline (history, video render) can find them."""
        input_path = tmp_path / "src.wav"
        input_path.write_bytes(b"FAKE")
        output_dir = tmp_path / "out"

        def fake_separate(_path):
            # audio-separator writes into the dir bound at Separator(output_dir=...)
            # — capture that dir from the most recent Separator() call below.
            work_dir = Path(fake_sep_cls.call_args.kwargs["output_dir"])
            (work_dir / "src_(Instrumental)_UVR-MDX-NET-Inst_HQ_4.wav").write_bytes(b"INST")
            (work_dir / "src_(Vocals)_UVR-MDX-NET-Inst_HQ_4.wav").write_bytes(b"VOX")
            return [
                "src_(Instrumental)_UVR-MDX-NET-Inst_HQ_4.wav",
                "src_(Vocals)_UVR-MDX-NET-Inst_HQ_4.wav",
            ]

        fake_sep = MagicMock()
        fake_sep.separate.side_effect = fake_separate
        fake_sep_cls = MagicMock(return_value=fake_sep)

        fake_soundfile = MagicMock()
        fake_soundfile.__len__ = MagicMock(return_value=44100 * 30)
        fake_soundfile.samplerate = 44100
        fake_soundfile_ctx = MagicMock()
        fake_soundfile_ctx.__enter__ = MagicMock(return_value=fake_soundfile)
        fake_soundfile_ctx.__exit__ = MagicMock(return_value=False)

        with patch(
            "yt_song_to_instrumental.separator.inst_hq_4_backend.Separator",
            fake_sep_cls,
        ), patch(
            "yt_song_to_instrumental.separator.inst_hq_4_backend.sf.SoundFile",
            return_value=fake_soundfile_ctx,
        ):
            backend = InstHQ4Backend()
            result = backend.separate(input_path, output_dir)

        assert result.instrumental_path == output_dir / "inst_hq_4" / "src" / "no_vocals.wav"
        assert result.vocals_path == output_dir / "inst_hq_4" / "src" / "vocals.wav"
        assert result.instrumental_path.read_bytes() == b"INST"
        assert result.vocals_path.read_bytes() == b"VOX"
        assert result.model_name == "UVR-MDX-NET Inst_HQ_4"
        assert result.duration_seconds == 30.0
        # The model was loaded with the correct filename.
        fake_sep.load_model.assert_called_once_with(model_filename="UVR-MDX-NET-Inst_HQ_4.onnx")

    def test_separate_raises_when_instrumental_stem_missing(self, tmp_path):
        input_path = tmp_path / "src.wav"
        input_path.write_bytes(b"FAKE")

        fake_sep = MagicMock()
        # Only vocals stem returned — instrumental is missing.
        fake_sep.separate.return_value = ["src_(Vocals)_X.wav"]
        fake_sep_cls = MagicMock(return_value=fake_sep)

        with patch(
            "yt_song_to_instrumental.separator.inst_hq_4_backend.Separator",
            fake_sep_cls,
        ):
            backend = InstHQ4Backend()
            with pytest.raises(FileNotFoundError, match="instrumental stem"):
                backend.separate(input_path, tmp_path / "out")
