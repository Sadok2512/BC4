"""Memory admission for concurrent NMF imports.

All values are read at each decision.  This is intentional: completing one
decoder changes both host and cgroup headroom, so a cached value is unsafe.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from pathlib import Path

from app.config import settings

MIB = 1024 * 1024


def _memavailable_bytes(path: Path = Path("/proc/meminfo")) -> int:
    for line in path.read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    raise RuntimeError("MemAvailable missing from /proc/meminfo")


def _cgroup_available_bytes(root: Path = Path("/sys/fs/cgroup")) -> int | None:
    maximum = (root / "memory.max")
    current = (root / "memory.current")
    if not maximum.is_file() or not current.is_file():
        return None
    raw_max = maximum.read_text().strip()
    if raw_max == "max":
        return None
    return max(0, int(raw_max) - int(current.read_text().strip()))


def available_memory_mb() -> int:
    host = _memavailable_bytes()
    cgroup = _cgroup_available_bytes()
    return min(host, cgroup) // MIB if cgroup is not None else host // MIB


def estimate_memory_mb(size_bytes: int, level: str) -> int:
    base, slope = (
        (settings.import_memory_base_mb_deep, settings.import_memory_slope_mb_per_mib_deep)
        if level == "deep"
        else (settings.import_memory_base_mb_light, settings.import_memory_slope_mb_per_mib_light)
    )
    return max(1, ceil(base + slope * size_bytes / MIB))


@dataclass(frozen=True)
class AdmissionDecision:
    decision: str
    available_mb: int
    estimate_mb: int
    running: int
    reason: str


def decide(size_bytes: int, level: str, running: int) -> AdmissionDecision:
    available = available_memory_mb()
    estimate = estimate_memory_mb(size_bytes, level)
    margin = settings.import_memory_margin_mb
    usable = available - settings.import_reserved_mb
    if available < margin:
        return AdmissionDecision("wait", available, estimate, running, "below_margin")
    if usable >= estimate + margin:
        return AdmissionDecision("start", available, estimate, running, "fits")
    if running == 0:
        return AdmissionDecision("start", available, estimate, running, "oversize_solo")
    return AdmissionDecision("wait", available, estimate, running, "insufficient_headroom")
