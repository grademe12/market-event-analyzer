from market_event_analyzer.classification import EventType


class DartEventTypeNormalizer:
    _RULES: tuple[tuple[tuple[str, ...], EventType], ...] = (
        (("단일판매", "공급계약"), EventType.SUPPLY_CONTRACT),
        (("유상증자",), EventType.CAPITAL_INCREASE),
        (("자기주식취득", "자기주식 취득"), EventType.SHARE_BUYBACK),
        (("배당",), EventType.DIVIDEND),
        (("영업(잠정)실적", "매출액또는손익구조", "사업보고서"), EventType.EARNINGS),
        (("합병", "영업양수", "영업양도"), EventType.MERGER_ACQUISITION),
        (("소송",), EventType.LAWSUIT),
        (("전환사채", "신주인수권부사채", "교환사채", "사채권발행"), EventType.DEBT_FINANCING),
        (("투자판단관련주요경영사항",), EventType.INVESTMENT_DECISION),
        (("대표이사변경", "임원ㆍ주요주주특정증권등소유상황보고서"), EventType.MANAGEMENT_CHANGE),
        (("최대주주변경", "주식등의대량보유상황보고서"), EventType.OWNERSHIP_CHANGE),
        (("회생절차", "파산", "부도", "상장폐지"), EventType.FINANCIAL_DISTRESS),
        (("증권신고서", "투자설명서", "효력발생안내"), EventType.SECURITIES_FILING),
    )

    def normalize(self, provider_event_name: str) -> EventType:
        name = provider_event_name.strip()
        if not name:
            return EventType.OTHER

        for keywords, event_type in self._RULES:
            if any(keyword in name for keyword in keywords):
                return event_type
        return EventType.OTHER
