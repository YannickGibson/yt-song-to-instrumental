from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SeparationResult:
    instrumental_path: Path
    vocals_path: Path | None
    model_name: str
    duration_seconds: float


class SeparatorBackend(ABC):
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def separate(self, input_path: Path, output_dir: Path) -> SeparationResult:
        ...

    @abstractmethod
    def gpu_required(self) -> bool:
        ...

    @abstractmethod
    def min_memory_gb(self) -> float:
        ...
