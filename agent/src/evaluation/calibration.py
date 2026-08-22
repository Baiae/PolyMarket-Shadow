"""Reliability-bin calibration summaries."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from forecasting.forecast import probability

ZERO = Decimal(0)
ONE = Decimal(1)


@dataclass(frozen=True, slots=True)
class CalibrationBin:
    lower: Decimal
    upper: Decimal
    count: int
    mean_probability: Decimal
    observed_yes_rate: Decimal

    @property
    def calibration_error(self) -> Decimal:
        return abs(self.mean_probability - self.observed_yes_rate)


def reliability_bins(
    samples: list[tuple[Decimal | str | float, bool | int]],
    *,
    bin_count: int = 10,
) -> list[CalibrationBin]:
    if bin_count < 2:
        raise ValueError("bin_count must be at least 2")
    buckets: list[list[tuple[Decimal, Decimal]]] = [[] for _ in range(bin_count)]
    for raw_probability, raw_outcome in samples:
        p = probability(raw_probability)
        outcome = ONE if raw_outcome is True or raw_outcome == 1 else ZERO
        if raw_outcome not in (True, False, 0, 1):
            raise ValueError("binary outcome must be bool, 0, or 1")
        index = min(int(p * bin_count), bin_count - 1)
        buckets[index].append((p, outcome))

    width = ONE / Decimal(bin_count)
    results: list[CalibrationBin] = []
    for index, bucket in enumerate(buckets):
        if not bucket:
            continue
        lower = Decimal(index) * width
        upper = ONE if index == bin_count - 1 else Decimal(index + 1) * width
        count = len(bucket)
        mean_probability = sum((p for p, _ in bucket), ZERO) / Decimal(count)
        observed_yes_rate = sum((outcome for _, outcome in bucket), ZERO) / Decimal(count)
        results.append(
            CalibrationBin(
                lower=lower,
                upper=upper,
                count=count,
                mean_probability=mean_probability,
                observed_yes_rate=observed_yes_rate,
            )
        )
    return results


def expected_calibration_error(bins: list[CalibrationBin]) -> Decimal:
    total = sum((item.count for item in bins), 0)
    if total <= 0:
        raise ValueError("at least one calibration sample is required")
    return sum(
        (
            item.calibration_error * Decimal(item.count) / Decimal(total)
            for item in bins
        ),
        ZERO,
    )
