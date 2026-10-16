"""Adapter over Zoom's official Realtime Media Streams SDK (PyPI ``rtms`` 1.1.0, MIT).

The SDK implements the RTMS signaling/media protocol and the join signature
(HMAC-SHA256 of ``client_id,meeting_uuid,rtms_stream_id`` with the client secret),
so this module does not re-implement any undocumented message format.

Only the transcript stream is consumed: RTMS delivers transcript text with
``userId``/``userName`` metadata, so no audio is buffered and no speech-to-text
runs. The SDK client is created through a factory so tests can substitute a fake.

Not verified against a live RTMS session (no RTMS-enabled account available);
in particular the unit of the SDK ``timestamp`` argument is recorded verbatim in
source metadata and only converted to an offset relative to the first segment.
"""

from __future__ import annotations

import contextlib
import importlib.util
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger(__name__)


def rtms_sdk_available() -> bool:
    return importlib.util.find_spec("rtms") is not None


@dataclass(frozen=True)
class RtmsJoinParams:
    meeting_uuid: str
    rtms_stream_id: str
    server_urls: str


@dataclass(frozen=True)
class RtmsTranscript:
    text: str
    timestamp: int | None
    user_id: str | None
    user_name: str | None


class RtmsClientLike(Protocol):
    def on_transcript_data(self, callback: Callable[..., Any]) -> Any: ...
    def on_leave(self, callback: Callable[..., Any]) -> Any: ...
    def join(self, **kwargs: Any) -> Any: ...
    def poll(self) -> Any: ...
    def leave(self) -> Any: ...


def default_client_factory() -> RtmsClientLike:
    import rtms  # official SDK; optional dependency (pip install "memo-hub-backend[zoom-rtms]")

    return rtms.Client()  # type: ignore[no-any-return]


class RtmsStream:
    """Runs one RTMS stream on its own thread until stopped or Zoom ends it."""

    def __init__(
        self,
        params: RtmsJoinParams,
        *,
        client_id: str,
        client_secret: str,
        on_transcript: Callable[[RtmsTranscript], None],
        on_state: Callable[[str, str], None],
        client_factory: Callable[[], RtmsClientLike] = default_client_factory,
        poll_interval_s: float = 0.01,
    ) -> None:
        self.params = params
        self._client_id = client_id
        self._client_secret = client_secret
        self._on_transcript = on_transcript
        self._on_state = on_state
        self._factory = client_factory
        self._poll = poll_interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name=f"rtms-{self.params.rtms_stream_id[:8]}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def join_thread(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def _handle_transcript(self, data: Any, size: Any = None, timestamp: Any = None, metadata: Any = None) -> None:
        try:
            raw = data.decode("utf-8", errors="replace") if isinstance(data, bytes | bytearray) else str(data)
            user_id = getattr(metadata, "userId", None)
            self._on_transcript(
                RtmsTranscript(
                    text=raw,
                    timestamp=int(timestamp) if isinstance(timestamp, int | float) else None,
                    user_id=str(user_id) if user_id not in (None, "") else None,
                    user_name=getattr(metadata, "userName", None) or None,
                )
            )
        except Exception:  # a bad segment must not kill the stream
            logger.exception("RTMS transcript callback failed")

    def _handle_leave(self, *_: Any) -> None:
        self._on_state("ended", "Zoom ended the RTMS stream")
        self._stop.set()

    def _run(self) -> None:
        client = None
        try:
            client = self._factory()
            client.on_transcript_data(self._handle_transcript)
            client.on_leave(self._handle_leave)
            ok = client.join(
                meeting_uuid=self.params.meeting_uuid,
                rtms_stream_id=self.params.rtms_stream_id,
                server_urls=self.params.server_urls,
                client=self._client_id,
                secret=self._client_secret,
            )
            if ok is False:
                self._on_state("failed", "Joining the RTMS stream failed")
                return
            self._on_state("connected", "Receiving the Zoom transcript stream")
            while not self._stop.is_set():
                client.poll()
                time.sleep(self._poll)
        except Exception as exc:
            logger.warning("RTMS stream error: %s", type(exc).__name__)
            self._on_state("interrupted", "The connection to Zoom RTMS was interrupted")
        finally:
            if client is not None:
                with contextlib.suppress(Exception):  # best-effort cleanup
                    client.leave()
