"""The common summary a check program writes and the `summary` reader reads (definitions.md § 5.3).

`{work}/summary.json`: ``{"quantities": {name: number | [numbers]}, "versions": {name: text}}``.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

FILE = "summary.json"


def write(work: Path, quantities: dict, versions: dict) -> Path:
    path = Path(work) / FILE
    tmp = path.with_name(f".{FILE}.tmp")
    tmp.write_text(json.dumps({"quantities": quantities, "versions": versions}, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    tmp.replace(path)
    return path


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def read(work: Path, engine: str, version: str) -> dict:
    """The quantities; ValueError, with the reason, when the summary is missing or malformed, or
    the program observed another version of ``engine`` than the pinned ``version``."""
    path = Path(work) / FILE
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"the check program wrote no {FILE}") from None
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{FILE} does not load: {exc}") from None
    quantities = document.get("quantities") if isinstance(document, dict) else None
    if not isinstance(quantities, dict):
        raise ValueError(f"{FILE} has no quantities")
    observed = (document.get("versions") or {}).get(engine)
    if observed is not None and observed != version:
        raise ValueError(f"the check ran {engine} {observed}; the environment pins {version}")
    for name, value in quantities.items():
        if not (_number(value) or isinstance(value, list) and value and all(_number(v) for v in value)):
            raise ValueError(f"{FILE}: {name} is not a finite number or a list of them: {value!r}")
    return quantities
