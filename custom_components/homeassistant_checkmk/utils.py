"""Utility helpers for filtering and parsing."""

import fnmatch
import re
import shlex


_PERF_VALUE_RE = re.compile(
    r"^(?P<value>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
    r"(?P<unit>[%a-zA-Z°/]+)?$"
)

_UNIT_MAP = {
    "%": "%",
    "b": "B",
    "kb": "kB",
    "mb": "MB",
    "gb": "GB",
    "tb": "TB",
    "s": "s",
    "ms": "ms",
    "us": "µs",
    "c": "°C",
    "°c": "°C",
    "v": "V",
    "a": "A",
    "w": "W",
    "hz": "Hz",
}


def split_terms(raw):
    return [term for term in raw.replace(",", " ").split() if term]


def match_any(value, patterns):
    """Match shell wildcards or ``re:``-prefixed regular expressions."""
    for pattern in patterns:
        if pattern.startswith("re:"):
            try:
                if re.search(pattern[3:], value, re.IGNORECASE):
                    return True
            except re.error:
                continue
        elif fnmatch.fnmatch(value.lower(), pattern.lower()):
            return True
    return False


def invalid_regex_patterns(patterns):
    """Return invalid ``re:`` patterns without raising during setup."""
    invalid = []
    for pattern in patterns:
        if not pattern.startswith("re:"):
            continue
        try:
            re.compile(pattern[3:])
        except re.error:
            invalid.append(pattern)
    return invalid


def selection_allows(value, selected, include_patterns, exclude_patterns):
    """Apply exact selections plus include/exclude wildcard or regex filters."""
    if not value:
        return False
    if (selected or include_patterns) and not (
        value in selected or match_any(value, include_patterns)
    ):
        return False
    return not match_any(value, exclude_patterns)


def metric_key(service_name, metric_name):
    """Return the stable value used by the metric multi-select."""
    return f"{service_name}::{metric_name}"


def metric_selection_allows(
    service_name, metric_name, selected, include_patterns, exclude_patterns
):
    """Filter a metric by exact service/metric key, metric name, or patterns."""
    key = metric_key(service_name, metric_name)
    candidates = (key, metric_name)
    if (selected or include_patterns) and not (
        key in selected
        or metric_name in selected
        or any(match_any(candidate, include_patterns) for candidate in candidates)
    ):
        return False
    return not any(match_any(candidate, exclude_patterns) for candidate in candidates)


def parse_perf_data(raw, service_name=None):
    """Parse Nagios/Checkmk performance data into numeric metrics.

    Checkmk uses ``name=value;warn;crit;min;max`` entries. Metric names may be
    quoted and values may carry a unit such as %, MB, s or °C.
    """
    if not isinstance(raw, str) or not raw.strip():
        return []

    try:
        entries = shlex.split(raw)
    except ValueError:
        return []

    metrics = []
    for entry in entries:
        if "=" not in entry:
            continue
        name, payload = entry.split("=", 1)
        fields = payload.split(";")
        match = _PERF_VALUE_RE.fullmatch(fields[0])
        if not name or match is None:
            continue
        unit = match.group("unit")
        normalized_unit = _UNIT_MAP.get(unit.lower(), unit) if unit else None
        metrics.append(
            {
                "name": name,
                "value": float(match.group("value")),
                "unit": normalized_unit or infer_metric_unit(service_name, name),
                "warning": _parse_limit(fields, 1),
                "critical": _parse_limit(fields, 2),
                "minimum": _parse_limit(fields, 3),
                "maximum": _parse_limit(fields, 4),
            }
        )
    return metrics


def infer_metric_unit(service_name, metric_name):
    """Infer units that Checkmk keeps in graph definitions, not perf_data."""
    service = (service_name or "").lower()
    metric = metric_name.lower()

    if metric.endswith("_percent") or metric in {"util", "disk_utilization"}:
        return "%"
    if "cpu utilization" in service and metric in {
        "user",
        "system",
        "wait",
        "nice",
        "steal",
        "guest",
    }:
        return "%"
    if "temperature" in service or metric in {"temp", "temperature"}:
        return "°C"
    if service == "memory" and metric != "mem_used_percent":
        return "B"
    if service.startswith("filesystem "):
        if metric in {"fs_used", "fs_free", "fs_size", "growth", "trend"}:
            return "MB"
    if metric == "uptime":
        return "s"
    if service.startswith("interface "):
        if metric in {"in", "out"}:
            return "B/s"
        if metric != "outqlen":
            return "1/s"
    if service == "disk io summary":
        if "throughput" in metric:
            return "B/s"
        if metric.endswith("wait") or metric == "disk_latency":
            return "s"
        if metric.endswith("request_size"):
            return "B"
        if metric.endswith("_ios"):
            return "1/s"
    return None


def _parse_limit(fields, index):
    if len(fields) <= index or not fields[index]:
        return None
    match = _PERF_VALUE_RE.fullmatch(fields[index])
    return float(match.group("value")) if match else None


def metric_device_class(unit):
    """Return a Home Assistant device class string for a known unit."""
    if unit in {"B", "kB", "MB", "GB", "TB"}:
        return "data_size"
    if unit in {"B/s", "kB/s", "MB/s", "GB/s", "bit/s", "kbit/s", "Mbit/s"}:
        return "data_rate"
    if unit in {"s", "ms", "µs"}:
        return "duration"
    if unit == "°C":
        return "temperature"
    if unit == "V":
        return "voltage"
    if unit == "A":
        return "current"
    if unit == "W":
        return "power"
    if unit == "Hz":
        return "frequency"
    return None
