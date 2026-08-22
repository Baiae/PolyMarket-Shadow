from pathlib import Path


def test_forecasting_core_has_no_execution_imports():
    root = Path(__file__).parents[1] / "src" / "forecasting"
    forbidden = ("paper_broker", "risk", "execution")
    for path in root.glob("*.py"):
        text = path.read_text()
        for token in forbidden:
            assert f"import {token}" not in text
            assert f"from {token}" not in text
