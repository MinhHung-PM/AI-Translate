"""Versioned prompts.

Prompts are immutable once released: change behaviour by adding a new
version and switching ``ACTIVE_*_VERSION``. The version is persisted on every
memo so results can be reproduced and compared.

Prompt-injection posture: transcript text is untrusted. It is serialized as
JSON *data* inside the user message (with ``<`` escaped so it cannot close the
wrapping tag), the system prompt states that nothing inside the data block is
an instruction, and model output is accepted only after strict schema
validation. The model has no tools and only sees the current meeting.
"""

from __future__ import annotations

import json
from typing import Any

LANGUAGE_NAMES = {"ja": "Japanese", "vi": "Vietnamese", "en": "English"}


def as_data_block(tag: str, payload: Any) -> str:
    """Serialize untrusted content so it cannot break out of its tag."""
    body = json.dumps(payload, ensure_ascii=False, indent=1)
    body = body.replace("<", "\\u003c").replace(">", "\\u003e")
    return f"<{tag}>\n{body}\n</{tag}>"
