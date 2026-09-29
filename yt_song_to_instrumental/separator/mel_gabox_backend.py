import logging
import os
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from audio_separator.separator import Separator

from yt_song_to_instrumental.constants import (
    AUDIO_SEPARATOR_MODELS_DIR,
    MEL_GABOX_BINARY_READ_MODE,
    MEL_GABOX_CACHE_ENV,
    MEL_GABOX_CPU_THREADS,
    MEL_GABOX_DEVICE,
    MEL_GABOX_DEVICE_ERROR,
    MEL_GABOX_DURATION_ERROR,
    MEL_GABOX_DURATION_TOLERANCE_SECONDS,
    MEL_GABOX_EMPTY_ERROR,
    MEL_GABOX_GPU_REQUIRED,
    MEL_GABOX_MDXC_OPTIONS,
    MEL_GABOX_MEMORY_GB,
    MEL_GABOX_MODEL_FILE,
    MEL_GABOX_NO_DEVICE_ERROR,
    MEL_GABOX_NONFINITE_ERROR,
    MEL_GABOX_OUTPUT_BASENAME,
    MEL_GABOX_OUTPUT_COUNT,
    MEL_GABOX_OUTPUT_ERROR,
    MEL_GABOX_OUTPUT_FILENAME,
    MEL_GABOX_OUTPUT_STEM,
    MEL_GABOX_PRECISION,
    MEL_GABOX_PRECISION_ERROR,
    MEL_GABOX_SEPARATOR_OPTIONS,
    MEL_GABOX_TEMP_PREFIX,
    MEL_GABOX_VALIDATION_BLOCK_SIZE,
    MEL_GABOX_VALIDATION_DTYPE,
    MODEL_DISPLAY_NAMES,
    MODEL_MEL_GABOX,
)
from yt_song_to_instrumental.separator.base import SeparationResult, SeparatorBackend

class MelGaboxBackend(SeparatorBackend):
    """Instrumental backend with explicit MPS/native-FP16 checks."""

    def name(self) -> str:
        return MODEL_DISPLAY_NAMES[MODEL_MEL_GABOX]

    def gpu_required(self) -> bool:
        return MEL_GABOX_GPU_REQUIRED

    def min_memory_gb(self) -> float:
        return MEL_GABOX_MEMORY_GB

    def _load(self, work_dir: Path) -> Separator:
        if not torch.backends.mps.is_available():
            raise RuntimeError(MEL_GABOX_NO_DEVICE_ERROR)
        torch.set_num_threads(MEL_GABOX_CPU_THREADS)
        cache_setting = os.environ.get(MEL_GABOX_CACHE_ENV)
        cache_dir = Path(cache_setting if cache_setting else AUDIO_SEPARATOR_MODELS_DIR).expanduser().resolve()
        cache_dir.mkdir(parents=True, exist_ok=True)
        separator = Separator(
            output_dir=str(work_dir),
            model_file_dir=str(cache_dir),
            mdxc_params=dict(MEL_GABOX_MDXC_OPTIONS),
            log_level=logging.WARNING,
            **MEL_GABOX_SEPARATOR_OPTIONS,
        )
        if separator.torch_device.type != MEL_GABOX_DEVICE:
            raise RuntimeError(MEL_GABOX_DEVICE_ERROR)
        separator.load_model(model_filename=MEL_GABOX_MODEL_FILE)
        parameters = tuple(separator.model_instance.model_run.parameters())
        if not parameters or any(parameter.device.type != MEL_GABOX_DEVICE for parameter in parameters):
            raise RuntimeError(MEL_GABOX_DEVICE_ERROR)
        # Native FP16 deliberately preserves some numerically sensitive
        # parameters in FP32. The first parameter need not be half precision.
        if separator.effective_precision != MEL_GABOX_PRECISION or not any(
            parameter.dtype == torch.float16 for parameter in parameters
        ):
            raise RuntimeError(MEL_GABOX_PRECISION_ERROR)
        return separator

    def separate(self, input_path: Path, output_dir: Path) -> SeparationResult:
        input_path = input_path.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        stem_dir = output_dir / MODEL_MEL_GABOX / input_path.stem
        stem_dir.mkdir(parents=True, exist_ok=True)
        destination = stem_dir / MEL_GABOX_OUTPUT_FILENAME
        expected_duration = sf.info(input_path).duration
        with tempfile.TemporaryDirectory(prefix=MEL_GABOX_TEMP_PREFIX, dir=output_dir) as temporary:
            work_dir = Path(temporary).resolve()
            separator = self._load(work_dir)
            produced = separator.separate(
                str(input_path),
                custom_output_names={MEL_GABOX_OUTPUT_STEM: MEL_GABOX_OUTPUT_BASENAME},
            )
            if len(produced) != MEL_GABOX_OUTPUT_COUNT:
                raise RuntimeError(MEL_GABOX_OUTPUT_ERROR)
            instrumental = Path(produced[0])
            if not instrumental.is_absolute():
                instrumental = work_dir / instrumental
            instrumental = instrumental.resolve()
            if not instrumental.is_relative_to(work_dir) or not instrumental.is_file():
                raise RuntimeError(MEL_GABOX_OUTPUT_ERROR)
            has_signal = False
            with sf.SoundFile(instrumental) as audio:
                duration = len(audio) / audio.samplerate
                for block in audio.blocks(blocksize=MEL_GABOX_VALIDATION_BLOCK_SIZE, dtype=MEL_GABOX_VALIDATION_DTYPE):
                    if not np.isfinite(block).all():
                        raise RuntimeError(MEL_GABOX_NONFINITE_ERROR)
                    has_signal = has_signal or bool(np.any(block))
            if not has_signal:
                raise RuntimeError(MEL_GABOX_EMPTY_ERROR)
            if abs(duration - expected_duration) > MEL_GABOX_DURATION_TOLERANCE_SECONDS:
                raise RuntimeError(MEL_GABOX_DURATION_ERROR)
            # Publish only a complete, validated file. Temporary and destination
            # directories share a filesystem, so replace is atomic.
            with instrumental.open(MEL_GABOX_BINARY_READ_MODE) as handle:
                os.fsync(handle.fileno())
            os.replace(instrumental, destination)
        return SeparationResult(
            instrumental_path=destination,
            vocals_path=None,
            model_name=self.name(),
            duration_seconds=duration,
        )
