from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from filenote.transcribe import (
    FakeTranscriber,
    FasterWhisperTranscriber,
    TranscribedSegment,
    to_transcript,
)


def test_fake_transcriber_and_to_transcript(tmp_path: Path) -> None:
    segments = [TranscribedSegment(0.0, 1.0, "Hello"), TranscribedSegment(1.5, 3.0, "World")]
    fake = FakeTranscriber(segments)
    out = fake.transcribe(tmp_path / "a.wav")
    assert out == segments and fake.paths == [tmp_path / "a.wav"]
    transcript = to_transcript(out, meeting_id="audio")
    assert transcript.segment_ids == ["s001", "s002"]
    assert transcript.segments[1].t == 1.5 and transcript.segments[1].speaker == "unknown"
    with pytest.raises(ValueError, match="no speech"):
        to_transcript([], meeting_id="x")


def test_faster_whisper_with_injected_model(tmp_path: Path) -> None:
    class Model:
        def transcribe(
            self, path: str, vad_filter: bool = True
        ) -> tuple[list[Any], dict[str, Any]]:
            return [
                SimpleNamespace(start=0, end=1, text=" Hi "),
                SimpleNamespace(start=1, end=2, text="  "),
            ], {}

    t = FasterWhisperTranscriber("base", model=Model())
    assert t.transcribe(tmp_path / "x.wav") == [TranscribedSegment(0.0, 1.0, "Hi")]
