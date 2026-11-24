"""SLURM: the commands that measure a machine, and the readers of their answers (jobs.md § 7, § 9.1).

Nodes are read one by one (`scontrol show node`), so node groups are exact and carry their
architecture, never a `48+` range; each QOS column is its own query beside the QOS name,
so a column one site's SLURM does not know costs no other; a pair a partition denies is
not a queue; and no queue is named or preferred.

Every reader returns plain data shaped like the record's parts, validated by the record
model (`femkit/jobs/record.py`). A fact that could not be read is ``{"unknown": reason}``;
a limit the scheduler states as none is ``"unlimited"`` (jobs.md § 9.1).
"""

from __future__ import annotations

import math
import re
from typing import Any

from femkit.core import process

UNLIMITED = "unlimited"
_NONE_WORDS = {"unlimited", "infinite", "n/a", ""}
_KEY_VALUE = re.compile(r"(\w+)=(.*?)(?=\s+\w+=|\s*$)")


def unknown(reason: str) -> dict:
    return {"unknown": reason}


# ------------------------------------------------------------------ running

def _ask(argv: list[str]) -> tuple[str | None, str]:
    """(stdout, "") when the command answered, else (None, why not)."""
    result = process.run(argv, timeout=120)
    if result.ok:
        return result.stdout, ""
    said = (result.stderr or result.stdout).strip().splitlines()
    return None, f"`{' '.join(argv[:3])}` failed" + (f": {said[0][:200]}" if said else "")


# ------------------------------------------------------------------ quantities

def wall_seconds(text: str) -> int:
    """SLURM's own wall spelling -> seconds: MM, MM:SS, HH:MM:SS, D-HH, D-HH:MM, D-HH:MM:SS."""
    text = text.strip()
    days = 0
    if "-" in text:
        d, _, text = text.partition("-")
        days = int(d)
        parts = [int(x) for x in text.split(":")] if text else [0]
        parts += [0] * (3 - len(parts))
        h, m, s = parts[:3]
    else:
        parts = [int(x) for x in text.split(":")]
        h, m, s = ((0, parts[0], 0) if len(parts) == 1 else
                   (0, parts[0], parts[1]) if len(parts) == 2 else parts[:3])
    return ((days * 24 + h) * 60 + m) * 60 + s


def wall(text: str | None) -> Any:
    """A wall limit as the scheduler states it: its own spelling, or ``unlimited``."""
    if text is None or text.strip().lower() in _NONE_WORDS:
        return UNLIMITED
    try:
        wall_seconds(text)
    except ValueError:
        return unknown(f"not a wall time: {text!r}")
    return text.strip()


def _wall_key(value: Any) -> float:
    return math.inf if value == UNLIMITED else wall_seconds(value)


def count(text: str | None) -> Any:
    """A count limit: a number, or ``unlimited`` when the scheduler states none."""
    if text is None or text.strip().lower() in _NONE_WORDS:
        return UNLIMITED
    try:
        return int(text)
    except ValueError:
        return unknown(f"not a number: {text!r}")


def mib(text: str) -> int:
    """A SLURM memory amount -> MiB; a bare number is MiB, as SLURM reads it."""
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([KMGTP]?)", text.strip().upper())
    if not m:
        raise ValueError(f"not a memory amount: {text!r}")
    scale = {"K": 1 / 1024, "": 1, "M": 1, "G": 1024, "T": 1024 ** 2, "P": 1024 ** 3}[m.group(2)]
    return int(float(m.group(1)) * scale)


def gres(text: str | None) -> dict[str, int]:
    """SLURM's gres spelling -> {type: count}: the affinity tail dropped, other generic
    resources ignored, an untyped count is type `gpu`, `(null)` is none."""
    out: dict[str, int] = {}
    g = (text or "").strip()
    if not g or g.lower() in ("(null)", "none"):
        return out
    g = re.sub(r"\(.*?\)", "", g)
    for token in g.split(","):
        parts = token.strip().split(":")
        if not parts or parts[0].lower() != "gpu" or len(parts) < 2:
            continue
        kind, number = (parts[1], parts[2]) if len(parts) >= 3 else ("gpu", parts[1])
        try:
            n = int(number)
        except ValueError:
            n = 1
        out[kind] = max(out.get(kind, 0), n)
    return out


def key_values(line: str) -> dict[str, str]:
    """One `scontrol show ... -o` line -> {key: value}; a value may hold spaces (`OS=`)."""
    return {m.group(1): m.group(2).strip() for m in _KEY_VALUE.finditer(line)}


# ------------------------------------------------------------------ readers

def read_cluster(text: str) -> str | None:
    """`scontrol show config` -> its ClusterName."""
    m = re.search(r"^\s*ClusterName\s*=\s*(\S+)", text, re.M)
    return m.group(1) if m else None


def read_partitions(text: str) -> dict[str, dict]:
    """`scontrol show partition -o` -> each partition's policy (jobs.md § 9.1)."""
    out: dict[str, dict] = {}
    for line in text.splitlines():
        kv = key_values(line)
        name = kv.get("PartitionName")
        if not name:
            continue
        policy: dict[str, Any] = {"max_time": wall(kv.get("MaxTime")),
                                  "max_cpus_per_node": count(kv.get("MaxCPUsPerNode"))}
        for key, field in (("DefMemPerCPU", "def_mem_per_cpu_mib"), ("DefMemPerNode", "def_mem_per_node_mib")):
            if key in kv:
                policy[field] = count(kv[key])
        allow = kv.get("AllowQos", "ALL")
        policy["allow_qos"] = "all" if allow.upper() == "ALL" else sorted(q for q in allow.split(",") if q)
        policy["deny_qos"] = sorted(q for q in kv.get("DenyQos", "").split(",") if q and q != "(null)")
        out[name] = policy
    return out


def read_nodes(text: str) -> dict[str, list[dict]]:
    """`scontrol show node -o` -> each partition's node groups: nodes alike in cores,
    memory, GPUs and architecture, counted (jobs.md § 9.1)."""
    groups: dict[str, dict[tuple, int]] = {}
    for line in text.splitlines():
        kv = key_values(line)
        if "NodeName" not in kv:
            continue
        key = (count(kv.get("CPUTot")) if kv.get("CPUTot") else None,
               count(kv.get("RealMemory")) if kv.get("RealMemory") else None,
               tuple(sorted(gres(kv.get("Gres")).items())),
               kv.get("Arch") or None)
        for partition in (p for p in kv.get("Partitions", "").split(",") if p):
            groups.setdefault(partition, {})
            groups[partition][key] = groups[partition].get(key, 0) + 1
    out: dict[str, list[dict]] = {}
    for partition, found in groups.items():
        rows = []
        for (cores, memory, gpus, arch), n in sorted(found.items(), key=lambda kv: str(kv[0])):
            rows.append({"count": n,
                         "cores": cores if cores is not None else unknown("CPUTot not stated"),
                         "memory_mib": memory if memory is not None else unknown("RealMemory not stated"),
                         "gpus": dict(gpus),
                         "architecture": arch or unknown("Arch not stated")})
        out[partition] = rows
    return out


def read_pairs(text: str) -> dict[str, str]:
    """A two-column `sacctmgr -P -n` answer (`Name|value`) -> {name: value}."""
    out = {}
    for line in text.splitlines():
        if "|" in line:
            name, _, value = line.partition("|")
            if name.strip():
                out[name.strip()] = value.strip()
    return out


def read_associations(text: str) -> dict[str, set[str]]:
    """`sacctmgr -P -n show assoc format=Partition,QOS` -> {partition: QOS}; an association
    naming no partition holds on every partition (key ""), and `no_submit` is not a QOS."""
    out: dict[str, set[str]] = {}
    for line in text.splitlines():
        if "|" not in line:
            continue
        partition, _, qos = line.partition("|")
        for q in qos.split(","):
            q = q.strip()
            if q and q != "no_submit":
                out.setdefault(partition.strip(), set()).add(q)
    return out


def tres_caps(text: str) -> dict[str, Any]:
    """A QOS's MaxTRES (per job) -> its cpu, memory and GPU caps; a term not stated is
    `unlimited`, a GPU cap stated only per GPU type is `unknown`, naming it."""
    terms = dict(t.split("=", 1) for t in text.split(",") if "=" in t)
    caps: dict[str, Any] = {"max_cpus": count(terms.get("cpu")), "max_memory_mib": UNLIMITED}
    if "mem" in terms:
        try:
            caps["max_memory_mib"] = mib(terms["mem"])
        except ValueError as exc:
            caps["max_memory_mib"] = unknown(str(exc))
    typed = sorted(k for k in terms if k.startswith("gres/gpu:"))
    caps["max_gpus"] = (count(terms["gres/gpu"]) if "gres/gpu" in terms
                        else unknown("capped per GPU type: " + ", ".join(typed)) if typed else UNLIMITED)
    return caps


# ------------------------------------------------------------------ the probe

#: The probe roles this reader reads, which the kind file names (jobs.md § 7): scontrol for the
#: cluster's name, partitions and nodes; sacctmgr for the QOS limits and the account's associations.
PROBES = ("control", "accounts")


def probe(paths: dict[str, Any], user: str) -> dict:
    """Run SLURM's probe commands and read them into the record's parts (jobs.md § 9.1).

    ``paths``: the kind's located commands by role (`control` = scontrol, `accounts` =
    sacctmgr), each a path or ``{"unknown": why}``. Returns ``identity``, ``partitions``,
    ``queues``, ``notes`` and ``sources``.
    """
    notes: list[str] = []
    sources: dict[str, str] = {}
    control, accounts = (paths.get(role) for role in PROBES)
    have_control, have_accounts = isinstance(control, str), isinstance(accounts, str)

    identity: Any = unknown("scontrol not found")
    partitions: Any = unknown("scontrol not found")
    if have_control:
        text, why = _ask([control, "show", "config"])
        name = read_cluster(text) if text is not None else None
        identity = name or unknown(why or "scontrol show config states no ClusterName")
        sources["identity"] = "scontrol show config"
        ptext, pwhy = _ask([control, "show", "partition", "-o"])
        ntext, nwhy = _ask([control, "show", "node", "-o"])
        if ptext is None:
            partitions = unknown(pwhy)
        else:
            policy = read_partitions(ptext)
            groups = read_nodes(ntext) if ntext is not None else {}
            if ntext is None:
                notes.append(f"node groups not read: {nwhy}")
            partitions = {name: {**pol, "node_groups": groups.get(name, [])} for name, pol in policy.items()}
            sources["partitions"] = "scontrol show partition, scontrol show node"

    queues: Any = unknown("no partitions were read")
    if isinstance(partitions, dict):
        queues = _queues(partitions, accounts if have_accounts else None, user, notes, sources)
    return {"identity": identity, "partitions": partitions, "queues": queues,
            "notes": notes, "sources": sources}


def _qos_column(accounts: str, column: str) -> tuple[dict[str, str] | None, str]:
    text, why = _ask([accounts, "-P", "-n", "show", "qos", f"format=Name,{column}"])
    return (read_pairs(text) if text is not None else None), why


def _queues(partitions: dict, accounts: str | None, user: str, notes: list, sources: dict) -> list[dict]:
    allowed: dict[str, set[str]] = {}
    reason = "sacctmgr not found"
    if accounts:
        text, why = _ask([accounts, "-P", "-n", "show", "assoc", f"user={user}", "format=Partition,QOS"])
        allowed = read_associations(text) if text is not None else {}
        reason = why or f"sacctmgr lists no association for {user}"
    walls = trs = submits = None
    if accounts and allowed:
        walls, why_w = _qos_column(accounts, "MaxWall")
        trs, why_t = _qos_column(accounts, "MaxTRES")
        submits, why_s = _qos_column(accounts, "MaxSubmitJobsPerUser")
        sources["queues"] = f"sacctmgr show assoc user={user}, sacctmgr show qos"
    if not allowed:
        notes.append(f"the account's QOS list could not be read ({reason}): each partition is one "
                     "queue with no QOS, and a job's header carries no QOS line")
    if allowed.get(""):
        notes.append("an association that names no partition is taken to hold on every partition")

    out = []
    for name, part in sorted(partitions.items()):
        if allowed:
            qos_here = sorted(allowed.get("", set()) | allowed.get(name, set()))
            if part["allow_qos"] != "all":
                qos_here = [q for q in qos_here if q in part["allow_qos"]]
            qos_here = [q for q in qos_here if q not in part["deny_qos"]]
        else:
            qos_here = [None]
        for qos in qos_here:
            out.append(_queue(name, part, qos, walls, trs, submits))
    return out


def _queue(partition: str, part: dict, qos: str | None, walls, trs, submits) -> dict:
    row: dict[str, Any] = {"partition": partition}
    no_qos = unknown("no QOS: the account's default applies")
    if qos is None:
        row.update(max_time=part["max_time"], max_cpus=no_qos, max_memory_mib=no_qos, max_gpus=no_qos,
                   max_submit_jobs_per_user=no_qos)
        return row
    row["qos"] = qos
    qos_wall = (wall(walls.get(qos)) if qos in walls else unknown(f"QOS {qos} not listed")) \
        if walls is not None else unknown("QOS walls not read")
    p_wall = part["max_time"]
    # The effective wall is the shorter of the two; with either unread it is unknown,
    # saying what the other allows.
    if isinstance(p_wall, dict) and isinstance(qos_wall, dict):
        row["max_time"] = p_wall
    elif isinstance(p_wall, dict):
        row["max_time"] = unknown(f"{p_wall['unknown']}; the QOS allows {qos_wall}")
    elif isinstance(qos_wall, dict):
        row["max_time"] = unknown(f"{qos_wall['unknown']}; the partition allows {p_wall}")
    else:
        row["max_time"] = min((p_wall, qos_wall), key=_wall_key)
    if trs is not None and qos in trs:
        row.update(tres_caps(trs[qos]))
    else:
        why = unknown(f"QOS {qos} not listed" if trs is not None else "QOS caps not read")
        row.update(max_cpus=why, max_memory_mib=why, max_gpus=why)
    row["max_submit_jobs_per_user"] = (count(submits.get(qos)) if qos in submits else unknown(f"QOS {qos} not listed")) \
        if submits is not None else unknown("this SLURM did not answer MaxSubmitJobsPerUser")
    return row
