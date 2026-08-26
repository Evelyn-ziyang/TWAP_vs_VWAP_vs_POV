"""Fetch the reference project's five-ticker, 5-minute research universe.

The reference repository uses AAPL, MSFT, AMZN, NVDA and SPY over roughly 60
trading days.  This standard-library wrapper creates one validated schema-v1
pickle per ticker with the same regular-hours convention as the local AAPL
fixture.  Network access is required.

Example
-------
python Data_example/fetch_reference_universe.py
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from data_fetching import build_dataset, download_yahoo, save_pickle  # noqa: E402


REFERENCE_REPOSITORY = "https://github.com/alicelmre2705/twap-vs-vwap-2026"
DEFAULT_SYMBOLS = ("AAPL", "MSFT", "AMZN", "NVDA", "SPY")
DEFAULT_OUTPUT_DIR = Path(__file__).with_name("reference_universe")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS))
    parser.add_argument("--interval", default="5m", choices=("1m", "2m", "5m", "15m", "30m", "60m"))
    parser.add_argument(
        "--range",
        dest="range_",
        default="3mo",
        help="Yahoo chart lookback; 3mo is filtered to the latest 60 complete sessions",
    )
    parser.add_argument("--sessions", type=int, default=60)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def fetch_universe(
    symbols: list[str],
    *,
    interval: str,
    range_: str,
    sessions: int,
    retries: int = 3,
) -> list[tuple[str, dict[str, Any]]]:
    """Download every symbol before writing anything, avoiding partial refreshes."""
    if sessions < 2:
        raise ValueError("sessions must be at least 2")
    normalized = [symbol.strip().upper() for symbol in symbols]
    if not normalized or any(not symbol for symbol in normalized):
        raise ValueError("symbols must contain at least one non-empty ticker")
    if len(set(normalized)) != len(normalized):
        raise ValueError("symbols must not contain duplicates")

    downloaded: list[tuple[str, dict[str, Any]]] = []
    for symbol in normalized:
        records, source_url = download_yahoo(symbol, interval, range_, retries=retries)
        dataset = build_dataset(
            records,
            symbol=symbol,
            interval=interval,
            sessions=sessions,
            provider="Yahoo Finance chart API",
            source_url=source_url,
        )
        downloaded.append((symbol, dataset))
    return downloaded


def save_universe(datasets: list[tuple[str, dict[str, Any]]], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "reference_repository": REFERENCE_REPOSITORY,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbols": {},
    }
    for symbol, dataset in datasets:
        path = output_dir / f"{symbol}_5m.pkl"
        save_pickle(dataset, path)
        metadata = dataset["metadata"]
        manifest["symbols"][symbol] = {
            "file": path.name,
            "bars": len(dataset["records"]),
            "sessions": len(metadata["session_bar_counts"]),
            "first_session": min(metadata["session_bar_counts"]),
            "last_session": max(metadata["session_bar_counts"]),
            "provider": metadata["provider"],
            "source_url": metadata["source_url"],
        }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def main() -> int:
    args = parse_args()
    datasets = fetch_universe(
        args.symbols,
        interval=args.interval,
        range_=args.range_,
        sessions=args.sessions,
        retries=args.retries,
    )
    manifest_path = save_universe(datasets, args.output_dir)
    for symbol, dataset in datasets:
        sessions = dataset["metadata"]["session_bar_counts"]
        print(f"{symbol}: {len(dataset['records'])} bars across {len(sessions)} sessions")
    print(f"manifest written to {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
