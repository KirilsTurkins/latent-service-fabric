"""Exact retained samples and explicitly named, deterministic statistics."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, localcontext
from typing import Any

from .common import require, text, uint

MAX_SAMPLES = 4_000_000


def decimal_string(value: Decimal) -> str:
    result = format(value, "f")
    return result.rstrip("0").rstrip(".") if "." in result else result


def distribution(values: list[int | Decimal]) -> dict[str, str]:
    require(bool(values), "missing-metric-samples")
    ordered = sorted(Decimal(value) for value in values)
    count = len(ordered)
    median = (ordered[(count - 1) // 2] + ordered[count // 2]) / 2
    deviations = sorted(abs(value - median) for value in ordered)
    mad = (deviations[(count - 1) // 2] + deviations[count // 2]) / 2
    with localcontext() as context:
        context.prec = 40
        mean = sum(ordered) / count
        variance = sum((value - mean) ** 2 for value in ordered) / count
        result = {
            "count": str(count), "minimum": decimal_string(ordered[0]),
            "median": decimal_string(median), "maximum": decimal_string(ordered[-1]),
            "p95": decimal_string(ordered[(95 * count + 99) // 100 - 1]),
            "p99": decimal_string(ordered[(99 * count + 99) // 100 - 1]),
            "mean": decimal_string(mean.quantize(Decimal("0.000001"))),
            "median_absolute_deviation": decimal_string(mad),
            "standard_deviation": decimal_string(variance.sqrt().quantize(Decimal("0.000001"))),
        }
    return result


class Measurements:
    """Finite numeric retention, with no trimming, downsampling or outlier deletion."""

    def __init__(self) -> None:
        self.values: dict[tuple[str, str, str], list[int]] = defaultdict(list)
        self.count = 0

    def add(self, name: str, boundary: str, unit: str, values: list[Any]) -> None:
        text(name, 128)
        text(boundary, 256)
        require(unit in ("ns", "us", "bytes", "count"), "invalid-measurement-unit")
        require(isinstance(values, list) and bool(values), "missing-metric-samples")
        self.count += len(values)
        require(self.count <= MAX_SAMPLES, "metric-sample-limit")
        converted = [uint(value) for value in values]
        self.values[(name, boundary, unit)].extend(converted)

    def summaries(self) -> list[dict[str, Any]]:
        return [{"name": name, "boundary": boundary, "unit": unit, "statistics": distribution(values)}
                for (name, boundary, unit), values in sorted(self.values.items())]
