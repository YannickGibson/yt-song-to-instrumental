from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
import soundfile as sf
import torch

from yt_song_to_instrumental.constants import (
    MEL_GABOX_CACHE_ENV,
    MEL_GABOX_MODEL_FILE,
    MODEL_MEL_GABOX,
)
from yt_song_to_instrumental.separator import get_separator
from yt_song_to_instrumental.separator import mel_gabox_backend as module


@pytest.fixture
def environment(tmp_path, monkeypatch):
    source = tmp_path / "source.wav"
    sf.write(source, np.full((4410, 2), 0.1, dtype=np.float32), 44100)
    monkeypatch.setenv(MEL_GABOX_CACHE_ENV, str(tmp_path / "model-cache"))
    monkeypatch.setattr(module.torch.backends.mps, "is_available", lambda: True)
    set_threads = MagicMock()
    monkeypatch.setattr(module.torch, "set_num_threads", set_threads)
    parameter = SimpleNamespace(device=SimpleNamespace(type="mps"), dtype=torch.float16)
    separator = MagicMock()
    separator.torch_device = SimpleNamespace(type="mps")
    separator.effective_precision = "native_fp16"
    separator.model_instance.model_run.parameters.side_effect = lambda: iter([parameter])
    constructor = MagicMock(return_value=separator)
    monkeypatch.setattr(module, "Separator", constructor)

    def write_stem(_source, custom_output_names):
        work = Path(constructor.call_args.kwargs["output_dir"])
        path = work / "instrumental.wav"
        sf.write(path, np.full((4410, 2), 0.05, dtype=np.float32), 44100)
        return [path.name]

    separator.separate.side_effect = write_stem
    return SimpleNamespace(source=source, out=tmp_path / "out", separator=separator,
                           constructor=constructor, parameter=parameter, set_threads=set_threads)


def test_factory_metadata_does_not_load_gpu(environment, monkeypatch):
    monkeypatch.setattr(module.torch.backends.mps, "is_available", lambda: False)
    backend = get_separator(MODEL_MEL_GABOX)
    assert isinstance(backend, module.MelGaboxBackend)
    assert backend.gpu_required() is True
    assert backend.min_memory_gb() == 8.0
    environment.constructor.assert_not_called()


@pytest.mark.parametrize("absolute", [False, True])
def test_selected_preset_and_canonical_output(environment, absolute):
    original = environment.separator.separate.side_effect

    def output_paths(source, custom_output_names):
        paths = original(source, custom_output_names)
        if absolute:
            return [str(Path(environment.constructor.call_args.kwargs["output_dir"]) / paths[0])]
        return paths

    environment.separator.separate.side_effect = output_paths
    result = module.MelGaboxBackend().separate(environment.source, environment.out)
    assert result.instrumental_path == environment.out / MODEL_MEL_GABOX / "source" / "no_vocals.wav"
    assert result.instrumental_path.is_file()
    assert result.vocals_path is None
    assert result.duration_seconds == pytest.approx(0.1)
    options = environment.constructor.call_args.kwargs
    assert options["use_native_fp16"] is True
    assert options["use_autocast"] is False
    assert options["use_soundfile"] is True
    assert options["normalization_threshold"] == 1.0
    assert options["amplification_threshold"] == 0.0
    assert options["output_single_stem"] == "Instrumental"
    assert options["mdxc_params"] == {"segment_size": 256, "override_model_segment_size": False,
                                      "batch_size": 1, "overlap": 4, "pitch_shift": 0}
    assert options["model_file_dir"] == str(environment.source.parent / "model-cache")
    environment.separator.load_model.assert_called_once_with(model_filename=MEL_GABOX_MODEL_FILE)
    environment.set_threads.assert_called_once_with(2)
    assert not Path(options["output_dir"]).exists()


def test_missing_mps_fails_before_constructing_separator(environment, monkeypatch):
    monkeypatch.setattr(module.torch.backends.mps, "is_available", lambda: False)
    with pytest.raises(RuntimeError, match="requires an available MPS"):
        module.MelGaboxBackend().separate(environment.source, environment.out)
    environment.constructor.assert_not_called()


def test_native_fp16_accepts_protected_fp32_first_parameter(environment):
    protected = SimpleNamespace(device=SimpleNamespace(type="mps"), dtype=torch.float32)
    environment.separator.model_instance.model_run.parameters.side_effect = lambda: iter([
        protected, environment.parameter,
    ])
    result = module.MelGaboxBackend().separate(environment.source, environment.out)
    assert result.instrumental_path.is_file()


@pytest.mark.parametrize("failure", ["auto_cpu", "model_cpu", "precision", "dtype"])
def test_incorrect_runtime_refuses_separation(environment, failure):
    if failure == "auto_cpu":
        environment.separator.torch_device = SimpleNamespace(type="cpu")
    elif failure == "model_cpu":
        environment.parameter.device.type = "cpu"
    elif failure == "precision":
        environment.separator.effective_precision = "fp32"
    else:
        environment.parameter.dtype = torch.float32
    with pytest.raises(RuntimeError, match="required"):
        module.MelGaboxBackend().separate(environment.source, environment.out)
    environment.separator.separate.assert_not_called()
    assert not list(environment.out.rglob("no_vocals.wav"))


@pytest.mark.parametrize("failure", ["missing", "multiple", "outside", "silent", "empty", "nonfinite", "duration"])
def test_failed_output_never_replaces_existing_master(environment, failure):
    destination = environment.out / MODEL_MEL_GABOX / "source" / "no_vocals.wav"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"previous-complete-master")

    def bad_output(_source, custom_output_names):
        work = Path(environment.constructor.call_args.kwargs["output_dir"])
        if failure == "missing":
            return ["missing.wav"]
        if failure == "multiple":
            return ["one.wav", "two.wav"]
        if failure == "outside":
            return [str(environment.source)]
        samples = np.full((4410, 2), 0.05, dtype=np.float32)
        if failure == "silent":
            samples[:] = 0
        elif failure == "empty":
            samples = samples[:0]
        elif failure == "nonfinite":
            samples[0, 0] = np.nan
        elif failure == "duration":
            samples = np.tile(samples, (4, 1))
        path = work / "instrumental.wav"
        sf.write(path, samples, 44100, subtype="FLOAT")
        return [str(path)]

    environment.separator.separate.side_effect = bad_output
    with pytest.raises(RuntimeError):
        module.MelGaboxBackend().separate(environment.source, environment.out)
    assert destination.read_bytes() == b"previous-complete-master"
    assert not Path(environment.constructor.call_args.kwargs["output_dir"]).exists()


def test_reused_backend_publishes_distinct_tracks(environment):
    backend = module.MelGaboxBackend()
    first = backend.separate(environment.source, environment.out)
    second_source = environment.source.with_name("second.wav")
    second_source.write_bytes(environment.source.read_bytes())
    second = backend.separate(second_source, environment.out)
    assert first.instrumental_path != second.instrumental_path
    assert first.instrumental_path.exists() and second.instrumental_path.exists()
    assert environment.constructor.call_count == 2
