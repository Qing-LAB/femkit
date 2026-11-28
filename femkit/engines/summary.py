"""The common summary a check program writes and the `summary` reader reads (definitions.md § 5.3).

`{work}/summary.json`: ``{"quantities": {name: number | [numbers]}, "versions": {name: text}}``.
`write` runs inside an environment, `read` in the control process, on what the runner read.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from femkit.engines import Output

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


def read(output: Output) -> dict:
    """The quantities; ValueError, with the reason, when the summary is missing or malformed, or
    states no version of what the environment pins — its engine, or a tool environment's own
    name — or another version than the pinned one."""
    held = output.written(FILE).get(FILE)
    if held is None:
        raise ValueError(f"the check program wrote no {FILE}")
    try:
        document = json.loads(held.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{FILE} does not load: {exc}") from None
    quantities = document.get("quantities") if isinstance(document, dict) else None
    if not isinstance(quantities, dict):
        raise ValueError(f"{FILE} has no quantities")
    versions = document.get("versions")
    observed = versions.get(output.product) if isinstance(versions, dict) else None
    if observed is None:
        raise ValueError(f"{FILE} states no version of {output.product}; the environment pins {output.version}")
    if observed != output.version:
        raise ValueError(f"the check ran {output.product} {observed}; the environment pins {output.version}")
    for name, value in quantities.items():
        if not (_number(value) or isinstance(value, list) and value and all(_number(v) for v in value)):
            raise ValueError(f"{FILE}: {name} is not a finite number or a list of them: {value!r}")
    return quantities
