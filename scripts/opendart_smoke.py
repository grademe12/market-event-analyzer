from market_event_analyzer.providers.opendart import OpenDartCollector


def main() -> None:
    items = OpenDartCollector.from_env().collect()

    print("OpenDART live smoke test: PASS")
    print(f"listed disclosures collected: {len(items)}")
    for item in items[:5]:
        symbol = item.symbols[0] if item.symbols else "-"
        print(f"- {symbol} | {item.headline} | {item.provider_item_id}")


if __name__ == "__main__":
    main()
