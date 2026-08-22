from pathlib import Path


SRC = Path(__file__).parents[1] / "src"


def test_research_core_has_no_execution_imports():
    forbidden = ("paper_broker", "risk", "execution")
    for package in ("forecasting", "evaluation"):
        for path in (SRC / package).glob("*.py"):
            text = path.read_text()
            for token in forbidden:
                assert f"import {token}" not in text
                assert f"from {token}" not in text


def test_paper_execution_core_has_no_forecasting_imports():
    paper_core = (
        SRC / "main.py",
        SRC / "paper_broker.py",
        SRC / "risk.py",
    )
    forbidden = ("forecasting", "evaluation")
    for path in paper_core:
        text = path.read_text()
        for token in forbidden:
            assert f"import {token}" not in text
            assert f"from {token}" not in text
