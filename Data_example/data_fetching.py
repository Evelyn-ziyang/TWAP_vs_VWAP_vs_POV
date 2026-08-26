"""Download and persist intraday OHLCV data for the execution examples.

The script deliberately uses only the Python standard library.  The default
source is Yahoo Finance's chart endpoint; ``--input-csv`` provides a fully
offline path for rebuilding the checked-in fixture.

Examples
--------
Refresh from Yahoo (network required)::

    python Data_example/data_fetching.py --symbol AAPL --interval 5m

Rebuild the repository fixture from the downloaded CSV cache::

    python Data_example/data_fetching.py \
        --input-csv Data_example/AAPL_5m_source.csv \
        --source-url https://raw.githubusercontent.com/getdata-finance/aapl-5m-ohlcv-stocks-historical-data/main/AAPL_5m.csv
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, time, timezone
import json
import math
from pathlib import Path
import pickle
import time as time_module
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


EXCHANGE_TZ = ZoneInfo("America/New_York")
REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)
DEFAULT_OUTPUT = Path(__file__).with_name("example.pkl")
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
INTERVAL_MINUTES = {"1m": 1, "2m": 2, "5m": 5, "15m": 15, "30m": 30, "60m": 60}


def _parse_timestamp(value: str) -> datetime:
    text = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _number(row: dict[str, Any], name: str) -> float:
    for candidate in (name, name.lower(), name.upper(), name.title()):
        if candidate in row and row[candidate] not in (None, ""):
            return float(row[candidate])
    raise ValueError(f"missing {name!r} column")


def _timestamp_text(row: dict[str, Any]) -> str:
    for candidate in ("timestamp", "Timestamp", "datetime", "Datetime", "date", "Date"):
        if candidate in row and row[candidate]:
            return str(row[candidate])
    raise ValueError("missing timestamp/datetime column")


def read_csv_records(path: Path) -> list[dict[str, Any]]:
    """Read a conventional OHLCV CSV without pandas."""
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row_number, row in enumerate(csv.DictReader(handle), start=2):
            try:
                stamp = _parse_timestamp(_timestamp_text(row))
                record = {
                    "timestamp": stamp.isoformat(),
                    "open": _number(row, "open"),
                    "high": _number(row, "high"),
                    "low": _number(row, "low"),
                    "close": _number(row, "close"),
                    "volume": _number(row, "volume"),
                }
                _validate_record(record)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid CSV row {row_number}: {exc}") from exc
            records.append(record)
    return records


def download_yahoo(
    symbol: str,
    interval: str,
    range_: str = "1mo",
    *,
    retries: int = 3,
) -> tuple[list[dict[str, Any]], str]:
    """Fetch OHLCV bars from Yahoo's public chart endpoint."""
    if retries <= 0:
        raise ValueError("retries must be positive")
    query = urlencode(
        {
            "range": range_,
            "interval": interval,
            "includePrePost": "false",
            "events": "div,splits",
        }
    )
    url = f"{YAHOO_CHART_URL.format(symbol=symbol)}?{query}"
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 execution-research-demo"})
    payload: dict[str, Any] | None = None
    for attempt in range(retries):
        try:
            with urlopen(request, timeout=30) as response:
                payload = json.load(response)
            break
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            if attempt + 1 == retries:
                raise
            time_module.sleep(2**attempt)
    assert payload is not None

    chart = payload.get("chart", {})
    if chart.get("error"):
        raise RuntimeError(f"Yahoo returned an error: {chart['error']}")
    results = chart.get("result") or []
    if not results:
        raise RuntimeError("Yahoo returned no chart result")

    result = results[0]
    timestamps = result.get("timestamp") or []
    quotes = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    fields = {name: quotes.get(name) or [] for name in ("open", "high", "low", "close", "volume")}
    records: list[dict[str, Any]] = []
    for index, epoch in enumerate(timestamps):
        values = {name: series[index] if index < len(series) else None for name, series in fields.items()}
        if any(value is None for value in values.values()):
            continue
        record = {
            "timestamp": datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat(),
            **{name: float(value) for name, value in values.items()},
        }
        _validate_record(record)
        records.append(record)
    return records, url


def _validate_record(record: dict[str, Any]) -> None:
    prices = [float(record[name]) for name in ("open", "high", "low", "close")]
    volume = float(record["volume"])
    if not all(math.isfinite(value) and value > 0 for value in prices):
        raise ValueError("OHLC prices must be finite and positive")
    if not math.isfinite(volume) or volume < 0:
        raise ValueError("volume must be finite and non-negative")
    if prices[1] < max(prices[0], prices[3]) or prices[2] > min(prices[0], prices[3]):
        raise ValueError("OHLC bar violates high/low bounds")


def select_regular_sessions(
    records: Iterable[dict[str, Any]], interval: str, sessions: int
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Keep the latest sufficiently complete US regular trading sessions."""
    if sessions <= 0:
        raise ValueError("sessions must be positive")
    if interval not in INTERVAL_MINUTES:
        raise ValueError(f"unsupported intraday interval: {interval}")

    by_day: dict[str, list[dict[str, Any]]] = {}
    for original in records:
        record = dict(original)
        stamp = _parse_timestamp(str(record["timestamp"]))
        local = stamp.astimezone(EXCHANGE_TZ)
        if REGULAR_OPEN <= local.time().replace(tzinfo=None) < REGULAR_CLOSE:
            record["timestamp"] = stamp.isoformat()
            record["session"] = local.date().isoformat()
            record["slot"] = local.strftime("%H:%M")
            by_day.setdefault(record["session"], []).append(record)

    expected = 390 // INTERVAL_MINUTES[interval]
    minimum = math.ceil(expected * 0.90)
    complete_days = [day for day, bars in sorted(by_day.items()) if len(bars) >= minimum]
    selected_days = complete_days[-sessions:]
    if len(selected_days) < min(2, sessions):
        raise ValueError(
            f"need at least {min(2, sessions)} usable sessions; found {len(selected_days)} "
            f"with >= {minimum}/{expected} bars"
        )

    selected: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for day in selected_days:
        bars = sorted(by_day[day], key=lambda item: str(item["timestamp"]))
        selected.extend(bars)
        counts[day] = len(bars)
    return selected, counts


def build_dataset(
    records: Iterable[dict[str, Any]],
    *,
    symbol: str,
    interval: str,
    sessions: int,
    provider: str,
    source_url: str,
) -> dict[str, Any]:
    selected, counts = select_regular_sessions(records, interval, sessions)
    return {
        "schema_version": 1,
        "metadata": {
            "symbol": symbol.upper(),
            "interval": interval,
            "provider": provider,
            "source_url": source_url,
            "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
            "exchange_timezone": str(EXCHANGE_TZ),
            "session_filter": "09:30 <= America/New_York < 16:00",
            "volume_unit": "provider-defined; verify before production use",
            "session_bar_counts": counts,
        },
        "records": selected,
    }


def save_pickle(dataset: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as handle:
        pickle.dump(dataset, handle, protocol=pickle.HIGHEST_PROTOCOL)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="AAPL")
    parser.add_argument("--interval", default="5m", choices=sorted(INTERVAL_MINUTES))
    parser.add_argument("--range", dest="range_", default="1mo", help="Yahoo lookback range")
    parser.add_argument("--retries", type=int, default=3, help="download attempts with exponential backoff")
    parser.add_argument("--sessions", type=int, default=6, help="latest usable sessions to retain")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--input-csv",
        type=Path,
        help="read an already downloaded OHLCV CSV instead of accessing Yahoo",
    )
    parser.add_argument("--source-url", default="", help="provenance URL for --input-csv")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.input_csv:
        records = read_csv_records(args.input_csv)
        provider = "public-csv-cache"
        source_url = args.source_url or str(args.input_csv)
    else:
        records, source_url = download_yahoo(
            args.symbol,
            args.interval,
            args.range_,
            retries=args.retries,
        )
        provider = "Yahoo Finance chart API"

    dataset = build_dataset(
        records,
        symbol=args.symbol,
        interval=args.interval,
        sessions=args.sessions,
        provider=provider,
        source_url=source_url,
    )
    save_pickle(dataset, args.output)
    metadata = dataset["metadata"]
    print(
        f"saved {len(dataset['records'])} {metadata['symbol']} {metadata['interval']} bars "
        f"across {len(metadata['session_bar_counts'])} sessions to {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
