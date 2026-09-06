"""Optional audio path: ``filenote transcribe meeting.wav`` through faster-whisper (extra
``[audio]``, imported lazily). Speaker labels are not produced by whisper; the segments come
out as ``unknown`` speakers and the adviser assigns names in the transcript text."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from filenote.schema import Segment, Transcript


@dataclass(frozen=True, slots=True)
class TranscribedSegment:
    start: float
    end: float
    text: str


class Transcriber(Protocol):
    def transcribe(self, path: Path) -> list[TranscribedSegment]: ...


class FakeTranscriber:
    """Returns scripted segments; records the paths it was asked to transcribe."""

    def __init__(self, segments: Sequence[TranscribedSegment]) -> None:
        self._segments = list(segments)
        self.paths: list[Path] = []

    def transcribe(self, path: Path) -> list[TranscribedSegment]:
        self.paths.append(path)
        return list(self._segments)


class FasterWhisperTranscriber:
    def __init__(
        self, model_size: str = "base", *, device: str = "auto", model: Any | None = None
    ) -> None:
        self._model_size = model_size
        self._device = device
        self._model: Any = model

    def transcribe(self, path: Path) -> list[TranscribedSegment]:
        if self._model is None:
            from faster_whisper import WhisperModel

            compute = "float16" if self._device == "cuda" else "int8"
            self._model = WhisperModel(self._model_size, device=self._device, compute_type=compute)
        segments, _info = self._model.transcribe(str(path), vad_filter=True)
        return [
            TranscribedSegment(float(s.start), float(s.end), str(s.text).strip())
            for s in segments
            if str(s.text).strip()
        ]


def to_transcript(
    segments: Sequence[TranscribedSegment], *, meeting_id: str, speaker: str = "unknown"
) -> Transcript:
    if not segments:
        msg = "no speech was transcribed"
        raise ValueError(msg)
    return Transcript(
        meeting_id=meeting_id,
        segments=[
            Segment(id=f"s{i:03d}", t=s.start, speaker=speaker, role="unknown", text=s.text)
            for i, s in enumerate(segments, start=1)
        ],
    )
