import json
from pathlib import Path

from market_event_analyzer.classification import EventType
from market_event_analyzer.contract import Direction, Impact
from market_event_analyzer.evaluation import load_evaluation_cases


def test_classifier_evaluation_fixture_loads() -> None:
    cases = load_evaluation_cases(Path("eval/classifier_cases.jsonl"))

    assert len(cases) == 6
    assert cases[0].event_type is EventType.SUPPLY_CONTRACT
    assert cases[0].acceptable_directions == (Direction.BUY,)
    assert cases[0].acceptable_impacts == (Impact.HIGH,)
    assert cases[0].expected_impact is Impact.HIGH


def test_real_corpus_case_supports_provenance_and_multiple_impacts(tmp_path) -> None:
    path = tmp_path / "real.jsonl"
    path.write_text(
        json.dumps(
            {
                "case_id": "opendart_20260922000123",
                "symbol": "005930",
                "event_type": "supply_contract",
                "headline": "테스트회사: 단일판매ㆍ공급계약체결",
                "body": "계약금액 1,000억원, 최근 매출액 대비 22%.",
                "acceptable_directions": ["BUY", "MIXED"],
                "acceptable_impacts": ["medium", "high"],
                "provider": "opendart",
                "source_item_id": "20260922000123",
                "source_url": "https://dart.fss.or.kr/example",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    (case,) = load_evaluation_cases(path)

    assert case.acceptable_directions == (Direction.BUY, Direction.MIXED)
    assert case.acceptable_impacts == (Impact.MEDIUM, Impact.HIGH)
    assert case.provider == "opendart"
    assert case.source_item_id == "20260922000123"
    assert case.source_url == "https://dart.fss.or.kr/example"


def test_expected_impact_property_rejects_multi_impact_case(tmp_path) -> None:
    path = tmp_path / "real.jsonl"
    path.write_text(
        json.dumps(
            {
                "case_id": "multi",
                "symbol": "005930",
                "event_type": "other",
                "headline": "headline",
                "body": "body",
                "acceptable_directions": ["MIXED"],
                "acceptable_impacts": ["low", "medium"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    (case,) = load_evaluation_cases(path)

    try:
        case.expected_impact
    except ValueError as exc:
        assert "multiple acceptable impacts" in str(exc)
    else:
        raise AssertionError("expected_impact should reject a multi-impact case")
