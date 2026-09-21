import pytest

from market_event_analyzer.classification import EventType
from market_event_analyzer.normalizers import DartEventTypeNormalizer


@pytest.mark.parametrize(
    ("report_name", "expected"),
    [
        ("단일판매ㆍ공급계약체결", EventType.SUPPLY_CONTRACT),
        ("유상증자결정", EventType.CAPITAL_INCREASE),
        ("자기주식취득결정", EventType.SHARE_BUYBACK),
        ("현금ㆍ현물배당결정", EventType.DIVIDEND),
        ("영업(잠정)실적(공정공시)", EventType.EARNINGS),
        ("회사합병 결정", EventType.MERGER_ACQUISITION),
        ("소송등의제기ㆍ신청", EventType.LAWSUIT),
        ("전환사채권발행결정", EventType.DEBT_FINANCING),
        ("투자판단관련주요경영사항", EventType.INVESTMENT_DECISION),
        ("대표이사변경", EventType.MANAGEMENT_CHANGE),
        ("최대주주변경", EventType.OWNERSHIP_CHANGE),
        ("회생절차개시신청", EventType.FINANCIAL_DISTRESS),
        ("증권신고서(지분증권)", EventType.SECURITIES_FILING),
        ("알 수 없는 공시", EventType.OTHER),
        ("", EventType.OTHER),
    ],
)
def test_dart_report_name_is_normalized(
    report_name: str,
    expected: EventType,
) -> None:
    assert DartEventTypeNormalizer().normalize(report_name) is expected
