"""Minimal, strict WAV handling for uploaded capture chunks.

The browser encodes 16-bit PCM mono WAV. Anything else is rejected before it
reaches a provider. Audio is processed in memory and never written to disk.
"""

from __future__ import annotations

import io
import wave
from dataclasses import dataclass

from app.core.errors import ValidationFailed

MIN_RATE, MAX_RATE = 8_000, 48_000


@dataclass(frozen=True)
class PcmAudio:
    frames: bytes  # 16-bit little-endian mono PCM
    sample_rate: int

    @property
    def duration_s(self) -> float:
        return len(self.frames) / 2 / self.sample_rate

    def slice(self, start_s: float, end_s: float) -> PcmAudio:
        a = max(0, int(start_s * self.sample_rate)) * 2
        b = min(len(self.frames), int(end_s * self.sample_rate) * 2)
        return PcmAudio(self.frames[a:b] if b > a else b"", self.sample_rate)

    def to_wav(self) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.sample_rate)
            w.writeframes(self.frames)
        return buf.getvalue()


def concat(parts: list[PcmAudio], max_s: float) -> PcmAudio | None:
    if not parts:
        return None
    rate = parts[0].sample_rate
    limit = int(max_s * rate) * 2
    out = b"".join(p.frames for p in parts if p.sample_rate == rate)[:limit]
    return PcmAudio(out, rate)


def parse_wav(data: bytes, *, max_seconds: float) -> PcmAudio:
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            channels, width, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
            if channels != 1 or width != 2 or not (MIN_RATE <= rate <= MAX_RATE):
                raise ValidationFailed("Audio must be 16-bit PCM mono WAV (8–48 kHz)")
            if n / rate > max_seconds + 0.5:
                raise ValidationFailed(f"Audio chunk is longer than {max_seconds:g} seconds")
            frames = w.readframes(n)
    except (wave.Error, EOFError) as exc:
        raise ValidationFailed("The uploaded audio is not a valid WAV file") from exc
    if len(frames) < 2 * rate // 10:
        raise ValidationFailed("Audio chunk is too short")
    return PcmAudio(frames, rate)
