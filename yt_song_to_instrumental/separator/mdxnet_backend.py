import logging
import subprocess
from pathlib import Path

from yt_song_to_instrumental.constants import MODEL_MDXNET, MODEL_DISPLAY_NAMES
from yt_song_to_instrumental.separator.base import SeparationResult, SeparatorBackend

logger = logging.getLogger(__name__)


class MDXNetBackend(SeparatorBackend):
    def name(self) -> str:
        return MODEL_DISPLAY_NAMES[MODEL_MDXNET]

    def gpu_required(self) -> bool:
        return False

    def min_memory_gb(self) -> float:
        return 2.0

    def separate(self, input_path: Path, output_dir: Path) -> SeparationResult:
        output_dir.mkdir(parents=True, exist_ok=True)

        instrumental_path = output_dir / f"{input_path.stem}_instrumental.wav"
        vocals_path = output_dir / f"{input_path.stem}_vocals.wav"

        cmd = [
            "python", "-m", "demucs",
            "--name", "mdx_extra",
            "--two-stems", "vocals",
            "-o", str(output_dir),
            str(input_path),
        ]

        logger.info("Running MDX-Net on %s", input_path.name)
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)

        stem_dir = output_dir / "mdx_extra" / input_path.stem
        instrumental_path = stem_dir / "no_vocals.wav"
        vocals_path = stem_dir / "vocals.wav"

        if not instrumental_path.exists():
            raise FileNotFoundError(f"MDX-Net did not produce instrumental at {instrumental_path}")

        duration = _get_duration(instrumental_path)

        return SeparationResult(
            instrumental_path=instrumental_path,
            vocals_path=vocals_path if vocals_path.exists() else None,
            model_name=self.name(),
            duration_seconds=duration,
        )


def _get_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())
