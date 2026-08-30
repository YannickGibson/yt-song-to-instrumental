import logging
import shutil
import tempfile
from pathlib import Path

import soundfile as sf
from audio_separator.separator import Separator

from yt_song_to_instrumental.constants import (
    AUDIO_SEPARATOR_MODELS_DIR,
    INST_HQ_4_MODEL_FILE,
    MODEL_DISPLAY_NAMES,
    MODEL_INST_HQ_4,
)
from yt_song_to_instrumental.separator.base import SeparationResult, SeparatorBackend

logger = logging.getLogger(__name__)


class InstHQ4Backend(SeparatorBackend):
    def __init__(self):
        self._separator: Separator | None = None

    def name(self) -> str:
        return MODEL_DISPLAY_NAMES[MODEL_INST_HQ_4]

    def gpu_required(self) -> bool:
        return False

    def min_memory_gb(self) -> float:
        # Measured ~2.45 GB peak RSS on Pi 4 during separation; round up.
        return 3.0

    def _load(self, work_dir: Path) -> Separator:
        # audio-separator binds its output_dir at construction time, so we
        # rebuild the Separator per call against a fresh per-track tmp dir.
        # The model itself is cached on disk in AUDIO_SEPARATOR_MODELS_DIR
        # after the first download (~59 MB) and is re-loaded into memory each
        # call. Re-loading is fast (~11 s) relative to separation (~17 min on Pi).
        models_dir = Path(AUDIO_SEPARATOR_MODELS_DIR)
        models_dir.mkdir(parents=True, exist_ok=True)
        sep = Separator(
            output_dir=str(work_dir),
            output_format="WAV",
            model_file_dir=str(models_dir),
            log_level=logging.WARNING,
        )
        sep.load_model(model_filename=INST_HQ_4_MODEL_FILE)
        return sep

    def separate(self, input_path: Path, output_dir: Path) -> SeparationResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        stem_dir = output_dir / MODEL_INST_HQ_4 / input_path.stem
        stem_dir.mkdir(parents=True, exist_ok=True)

        instrumental_path = stem_dir / "no_vocals.wav"
        vocals_path = stem_dir / "vocals.wav"

        logger.info("Running %s on %s", self.name(), input_path.name)

        with tempfile.TemporaryDirectory(prefix="inst_hq_4_", dir=str(output_dir)) as work:
            work_dir = Path(work)
            sep = self._load(work_dir)
            produced = sep.separate(str(input_path))
            produced_paths = [work_dir / name for name in produced]

            inst_src = _find_by_marker(produced_paths, "(Instrumental)")
            vocals_src = _find_by_marker(produced_paths, "(Vocals)")
            if not inst_src:
                raise FileNotFoundError(
                    f"{self.name()} did not produce an instrumental stem; got {produced}"
                )

            shutil.move(str(inst_src), instrumental_path)
            if vocals_src:
                shutil.move(str(vocals_src), vocals_path)

        with sf.SoundFile(str(instrumental_path)) as f:
            duration = len(f) / f.samplerate

        return SeparationResult(
            instrumental_path=instrumental_path,
            vocals_path=vocals_path if vocals_path.exists() else None,
            model_name=self.name(),
            duration_seconds=duration,
        )


def _find_by_marker(paths: list[Path], marker: str) -> Path | None:
    for p in paths:
        if marker in p.name:
            return p
    return None
