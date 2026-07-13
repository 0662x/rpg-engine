from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json_sha256(value: Any) -> str:
    wire = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(wire).hexdigest()
