import logging
from pathlib import Path

import soundfile as sf
import torch
from demucs.apply import apply_model
from demucs.audio import convert_audio
from demucs.pretrained import get_model

from yt_song_to_instrumental.constants import MODEL_DEMUCS, MODEL_DISPLAY_NAMES
from yt_song_to_instrumental.separator.base import SeparationResult, SeparatorBackend

logger = logging.getLogger(__name__)


class DemucsBackend(SeparatorBackend):
    def __init__(self):
        self._model = None

    def name(self) -> str:
        return MODEL_DISPLAY_NAMES[MODEL_DEMUCS]

    def gpu_required(self) -> bool:
        return False

    def min_memory_gb(self) -> float:
        return 4.0

    def _load_model(self):
        if self._model is None:
            logger.info("Loading HTDemucs model...")
            self._model = get_model("htdemucs")
            self._model.eval()
        return self._model

    def separate(self, input_path: Path, output_dir: Path) -> SeparationResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        model = self._load_model()

        logger.info("Running Demucs on %s", input_path.name)

        wav, sr = sf.read(str(input_path), dtype="float32")
        wav = torch.from_numpy(wav.T)
        if wav.dim() == 1:
            wav = wav.unsqueeze(0)

        wav = convert_audio(wav, sr, model.samplerate, model.audio_channels)

        with torch.no_grad():
            sources = apply_model(model, wav.unsqueeze(0), progress=True)[0]

        vocals_idx = model.sources.index("vocals")
        vocals = sources[vocals_idx]
        instrumental = wav - vocals

        stem_dir = output_dir / "htdemucs" / input_path.stem
        stem_dir.mkdir(parents=True, exist_ok=True)

        instrumental_path = stem_dir / "no_vocals.wav"
        vocals_path = stem_dir / "vocals.wav"

        instrumental_np = instrumental.cpu().numpy().T
        vocals_np = vocals.cpu().numpy().T

        sf.write(str(instrumental_path), instrumental_np, model.samplerate)
        sf.write(str(vocals_path), vocals_np, model.samplerate)

        duration = len(instrumental_np) / model.samplerate

        return SeparationResult(
            instrumental_path=instrumental_path,
            vocals_path=vocals_path,
            model_name=self.name(),
            duration_seconds=duration,
        )
