from decimal import Decimal

from evaluation.calibration import expected_calibration_error, reliability_bins


def test_reliability_bins_report_observed_frequency():
    bins = reliability_bins(
        [
            ("0.1", False),
            ("0.2", False),
            ("0.8", True),
            ("0.9", True),
        ],
        bin_count=2,
    )
    assert len(bins) == 2
    assert bins[0].observed_yes_rate == Decimal("0")
    assert bins[1].observed_yes_rate == Decimal("1")
    assert all(item.count == 2 for item in bins)
    assert expected_calibration_error(bins) == Decimal("0.15")
