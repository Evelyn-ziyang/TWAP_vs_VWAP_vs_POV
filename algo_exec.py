"""Research-grade TWAP, VWAP and POV schedules with a deterministic backtest.

This module is intentionally broker-agnostic: it creates child-order targets and
simulates fills against OHLCV bars.  It does *not* submit live orders.

Run the bundled out-of-sample example with::

    python algo_exec.py --data Data_example/example.pkl
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import json
import math
from pathlib import Path
import pickle
from statistics import median
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo


EXCHANGE_TZ = ZoneInfo("America/New_York")
DEFAULT_DATA_PATH = Path(__file__).with_name("Data_example") / "example.pkl"
DEFAULT_RESULTS_PATH = Path(__file__).with_name("Data_example") / "backtest_results.json"


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def sign(self) -> int:
        """Return +1 for buy costs and -1 for sell costs."""
        return 1 if self is Side.BUY else -1

    @classmethod
    def parse(cls, value: str | "Side") -> "Side":
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).upper())
        except ValueError as exc:
            raise ValueError("side must be BUY or SELL") from exc


@dataclass(frozen=True)
class ExecutionConfig:
    total_qty: int = 5_000
    side: Side = Side.BUY
    pov_rate: float = 0.10
    lot_size: int = 1
    max_participation_rate: float = 0.20
    half_spread_bps: float = 0.50
    impact_coefficient_bps: float = 10.0
    fee_per_share: float = 0.0035

    def validated(self) -> "ExecutionConfig":
        _validate_quantity(self.total_qty)
        if self.total_qty == 0:
            raise ValueError("execution total_qty must be positive")
        _validate_lot_size(self.total_qty, self.lot_size)
        Side.parse(self.side)
        if not 0 < self.pov_rate <= 1:
            raise ValueError("pov_rate must be in (0, 1]")
        if not 0 < self.max_participation_rate <= 1:
            raise ValueError("max_participation_rate must be in (0, 1]")
        for name in ("half_spread_bps", "impact_coefficient_bps", "fee_per_share"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        return self


@dataclass(frozen=True)
class Fill:
    timestamp: str
    target_qty: int
    qty: int
    market_volume: float
    participation_rate: float
    reference_price: float
    fill_price: float
    spread_cost: float
    impact_cost: float
    fees: float


@dataclass(frozen=True)
class BacktestResult:
    algorithm: str
    side: str
    test_session: str
    requested_qty: int
    executed_qty: int
    remaining_qty: int
    completion_rate: float
    child_orders: int
    average_execution_price: float
    arrival_price: float
    market_vwap: float
    arrival_shortfall_bps: float
    vwap_slippage_bps: float
    spread_cost: float
    impact_cost: float
    fees: float
    total_modelled_cost: float
    fills: tuple[Fill, ...]

    def summary(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("fills")
        return payload


def _validate_quantity(total_qty: int) -> None:
    if isinstance(total_qty, bool) or not isinstance(total_qty, int) or total_qty < 0:
        raise ValueError("total_qty must be a non-negative integer")


def _validate_lot_size(total_qty: int, lot_size: int) -> None:
    if isinstance(lot_size, bool) or not isinstance(lot_size, int) or lot_size <= 0:
        raise ValueError("lot_size must be a positive integer")
    if total_qty % lot_size:
        raise ValueError("total_qty must be divisible by lot_size")


def _validated_weights(weights: Sequence[float]) -> list[float]:
    if not weights:
        raise ValueError("weights must not be empty")
    parsed = [float(weight) for weight in weights]
    if any(not math.isfinite(weight) or weight < 0 for weight in parsed):
        raise ValueError("weights must be finite and non-negative")
    total_weight = sum(parsed)
    if not math.isfinite(total_weight) or total_weight <= 0:
        raise ValueError("at least one weight must be positive")
    return parsed


def allocate_integer(total_qty: int, weights: Sequence[float], lot_size: int = 1) -> list[int]:
    """Allocate quantity proportionally using the largest-remainder method.

    The result is deterministic, non-negative, lot-aligned and sums exactly to
    ``total_qty``.  Ties are resolved by earlier bucket index.
    """
    _validate_quantity(total_qty)
    _validate_lot_size(total_qty, lot_size)
    parsed = _validated_weights(weights)
    if total_qty == 0:
        return [0] * len(parsed)

    units = total_qty // lot_size
    scale = sum(parsed)
    raw_units = [units * weight / scale for weight in parsed]
    base_units = [math.floor(value) for value in raw_units]
    remainder = units - sum(base_units)
    ranking = sorted(
        range(len(parsed)),
        key=lambda index: (-(raw_units[index] - base_units[index]), index),
    )
    for index in ranking[:remainder]:
        base_units[index] += 1
    return [value * lot_size for value in base_units]


def twap(total_qty: int, buckets: int, lot_size: int = 1) -> list[int]:
    """Return an equal-time child-order schedule."""
    if isinstance(buckets, bool) or not isinstance(buckets, int) or buckets <= 0:
        raise ValueError("buckets must be a positive integer")
    return allocate_integer(total_qty, [1.0] * buckets, lot_size)


def vwap(total_qty: int, volume_profile: Sequence[float], lot_size: int = 1) -> list[int]:
    """Return a schedule proportional to a forecast volume profile."""
    return allocate_integer(total_qty, volume_profile, lot_size)


def pov(
    total_qty: int,
    market_volumes: Sequence[float],
    participation_rate: float,
    lot_size: int = 1,
) -> list[int]:
    """Generate an online-style percent-of-volume schedule.

    ``market_volumes`` is treated as exogenous printed volume.  Each bucket is
    capped at ``floor(volume * participation_rate / lot_size) * lot_size`` and
    the order stops after reaching ``total_qty``.  It may therefore finish with
    residual quantity when market volume is insufficient.
    """
    _validate_quantity(total_qty)
    _validate_lot_size(total_qty, lot_size)
    if not math.isfinite(float(participation_rate)) or not 0 < participation_rate <= 1:
        raise ValueError("participation_rate must be finite and in (0, 1]")
    parsed_volumes = [float(volume) for volume in market_volumes]
    if not parsed_volumes:
        raise ValueError("market_volumes must not be empty")
    if any(not math.isfinite(volume) or volume < 0 for volume in parsed_volumes):
        raise ValueError("market volumes must be finite and non-negative")

    remaining = total_qty
    schedule: list[int] = []
    for volume in parsed_volumes:
        capacity = math.floor(volume * participation_rate / lot_size) * lot_size
        quantity = min(capacity, remaining)
        schedule.append(quantity)
        remaining -= quantity
    return schedule


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        stamp = value
    else:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def _validated_record(original: Mapping[str, Any]) -> dict[str, Any]:
    required = ("timestamp", "open", "high", "low", "close", "volume")
    missing = [name for name in required if name not in original]
    if missing:
        raise ValueError(f"market record missing fields: {', '.join(missing)}")
    stamp = _parse_timestamp(original["timestamp"])
    prices = {name: float(original[name]) for name in ("open", "high", "low", "close")}
    volume = float(original["volume"])
    if any(not math.isfinite(value) or value <= 0 for value in prices.values()):
        raise ValueError("prices must be finite and positive")
    if not math.isfinite(volume) or volume < 0:
        raise ValueError("volume must be finite and non-negative")
    if prices["high"] < max(prices["open"], prices["close"]):
        raise ValueError("high is below open/close")
    if prices["low"] > min(prices["open"], prices["close"]):
        raise ValueError("low is above open/close")
    local = stamp.astimezone(EXCHANGE_TZ)
    return {
        "timestamp": stamp.isoformat(),
        **prices,
        "volume": volume,
        "session": str(original.get("session") or local.date().isoformat()),
        "slot": str(original.get("slot") or local.strftime("%H:%M")),
    }


def load_dataset(path: str | Path = DEFAULT_DATA_PATH) -> dict[str, Any]:
    """Load the trusted local pickle and validate its schema and records."""
    with Path(path).open("rb") as handle:
        payload = pickle.load(handle)  # nosec B301: repository-owned local fixture
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("unsupported dataset schema")
    raw_records = payload.get("records")
    if not isinstance(raw_records, list) or not raw_records:
        raise ValueError("dataset contains no records")
    records = sorted((_validated_record(record) for record in raw_records), key=lambda row: row["timestamp"])
    return {**payload, "records": records}


def split_train_test(records: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Use all but the final session for training and the final session for test."""
    validated = [_validated_record(record) for record in records]
    sessions = sorted({record["session"] for record in validated})
    if len(sessions) < 2:
        raise ValueError("at least two sessions are required for train/test split")
    test_session = sessions[-1]
    train = [record for record in validated if record["session"] != test_session]
    test = [record for record in validated if record["session"] == test_session]
    return train, test


def build_volume_profile(
    training_records: Sequence[Mapping[str, Any]],
    target_records: Sequence[Mapping[str, Any]],
) -> list[float]:
    """Estimate median historical volume share for each target time slot."""
    training = [_validated_record(record) for record in training_records]
    target = [_validated_record(record) for record in target_records]
    if not training or not target:
        raise ValueError("training and target records must not be empty")

    by_session: dict[str, list[dict[str, Any]]] = {}
    for record in training:
        by_session.setdefault(record["session"], []).append(record)

    shares_by_slot: dict[str, list[float]] = {}
    for bars in by_session.values():
        total_volume = sum(record["volume"] for record in bars)
        if total_volume <= 0:
            continue
        for record in bars:
            shares_by_slot.setdefault(record["slot"], []).append(record["volume"] / total_volume)
    weights = [median(shares_by_slot.get(record["slot"], [0.0])) for record in target]
    if sum(weights) <= 0:
        raise ValueError("historical records do not cover target time slots")
    return [weight / sum(weights) for weight in weights]


def _typical_price(bar: Mapping[str, Any]) -> float:
    return (float(bar["high"]) + float(bar["low"]) + float(bar["close"])) / 3.0


def simulate_execution(
    algorithm: str,
    target_schedule: Sequence[int],
    test_records: Sequence[Mapping[str, Any]],
    config: ExecutionConfig,
) -> BacktestResult:
    """Simulate fills, rolling unfilled target quantity to later bars."""
    config.validated()
    side = Side.parse(config.side)
    bars = [_validated_record(record) for record in test_records]
    if not bars or len(target_schedule) != len(bars):
        raise ValueError("schedule length must equal the number of test records")
    if any(isinstance(qty, bool) or not isinstance(qty, int) or qty < 0 for qty in target_schedule):
        raise ValueError("schedule quantities must be non-negative integers")
    if sum(target_schedule) > config.total_qty:
        raise ValueError("schedule exceeds configured total quantity")

    fills: list[Fill] = []
    carry = 0
    executed = 0
    for bar, target in zip(bars, target_schedule):
        carry += target
        remaining = config.total_qty - executed
        volume = float(bar["volume"])
        capacity = math.floor(volume * config.max_participation_rate / config.lot_size) * config.lot_size
        quantity = min(carry, capacity, remaining)
        if quantity <= 0:
            continue
        carry -= quantity
        executed += quantity

        reference = _typical_price(bar)
        participation = quantity / volume if volume > 0 else 0.0
        impact_bps = config.impact_coefficient_bps * math.sqrt(participation)
        adverse_move = (config.half_spread_bps + impact_bps) / 10_000.0
        fill_price = reference * (1 + side.sign * adverse_move)
        spread_cost = quantity * reference * config.half_spread_bps / 10_000.0
        impact_cost = quantity * reference * impact_bps / 10_000.0
        fills.append(
            Fill(
                timestamp=str(bar["timestamp"]),
                target_qty=target,
                qty=quantity,
                market_volume=volume,
                participation_rate=participation,
                reference_price=reference,
                fill_price=fill_price,
                spread_cost=spread_cost,
                impact_cost=impact_cost,
                fees=quantity * config.fee_per_share,
            )
        )

    if not fills:
        raise ValueError("execution generated no fills")

    total_notional = sum(fill.qty * fill.fill_price for fill in fills)
    average_price = total_notional / executed
    market_volume = sum(float(bar["volume"]) for bar in bars)
    if market_volume <= 0:
        raise ValueError("test session has zero market volume")
    market_vwap = sum(_typical_price(bar) * float(bar["volume"]) for bar in bars) / market_volume
    arrival = float(bars[0]["open"])
    fees = sum(fill.fees for fill in fills)
    fee_bps = fees / (arrival * executed) * 10_000.0
    arrival_shortfall = side.sign * (average_price - arrival) / arrival * 10_000.0 + fee_bps
    vwap_slippage = side.sign * (average_price - market_vwap) / market_vwap * 10_000.0 + fee_bps
    spread_cost = sum(fill.spread_cost for fill in fills)
    impact_cost = sum(fill.impact_cost for fill in fills)

    return BacktestResult(
        algorithm=algorithm,
        side=side.value,
        test_session=str(bars[0]["session"]),
        requested_qty=config.total_qty,
        executed_qty=executed,
        remaining_qty=config.total_qty - executed,
        completion_rate=executed / config.total_qty if config.total_qty else 1.0,
        child_orders=len(fills),
        average_execution_price=average_price,
        arrival_price=arrival,
        market_vwap=market_vwap,
        arrival_shortfall_bps=arrival_shortfall,
        vwap_slippage_bps=vwap_slippage,
        spread_cost=spread_cost,
        impact_cost=impact_cost,
        fees=fees,
        total_modelled_cost=spread_cost + impact_cost + fees,
        fills=tuple(fills),
    )


def run_backtest(dataset: Mapping[str, Any], config: ExecutionConfig) -> dict[str, BacktestResult]:
    """Run all algorithms on the final session without VWAP-profile leakage."""
    config.validated()
    records = dataset.get("records")
    if not isinstance(records, list):
        raise ValueError("dataset records must be a list")
    training, test = split_train_test(records)
    buckets = len(test)
    profile = build_volume_profile(training, test)
    schedules = {
        "TWAP": twap(config.total_qty, buckets, config.lot_size),
        "VWAP": vwap(config.total_qty, profile, config.lot_size),
        "POV": pov(
            config.total_qty,
            [float(record["volume"]) for record in test],
            config.pov_rate,
            config.lot_size,
        ),
    }
    return {
        name: simulate_execution(name, schedule, test, config)
        for name, schedule in schedules.items()
    }


def write_results(
    results: Mapping[str, BacktestResult],
    dataset: Mapping[str, Any],
    config: ExecutionConfig,
    output: Path,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "methodology": {
            "train_test": "all prior sessions train; final session test",
            "bar_reference_price": "(high + low + close) / 3",
            "market_benchmark": "volume-weighted bar reference price",
            "impact_bps": "impact_coefficient_bps * sqrt(child_qty / bar_volume)",
            "lower_slippage_is_better": True,
        },
        "dataset_metadata": dataset.get("metadata", {}),
        "config": {**asdict(config), "side": Side.parse(config.side).value},
        "results": {name: result.summary() for name, result in results.items()},
    }
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _print_results(results: Mapping[str, BacktestResult]) -> None:
    header = (
        f"{'Algo':<6} {'Done':>9} {'AvgPx':>11} {'Arrival bp':>12} "
        f"{'VWAP bp':>10} {'ModelCost':>12}"
    )
    print(header)
    print("-" * len(header))
    for name, result in results.items():
        print(
            f"{name:<6} {result.completion_rate:>8.1%} {result.average_execution_price:>11.4f} "
            f"{result.arrival_shortfall_bps:>12.2f} {result.vwap_slippage_bps:>10.2f} "
            f"{result.total_modelled_cost:>12.2f}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_PATH)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS_PATH)
    parser.add_argument("--qty", type=int, default=5_000)
    parser.add_argument("--side", choices=[side.value for side in Side], default=Side.BUY.value)
    parser.add_argument("--pov-rate", type=float, default=0.10)
    parser.add_argument("--max-participation", type=float, default=0.20)
    parser.add_argument("--half-spread-bps", type=float, default=0.50)
    parser.add_argument("--impact-bps", type=float, default=10.0)
    parser.add_argument("--fee-per-share", type=float, default=0.0035)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = ExecutionConfig(
        total_qty=args.qty,
        side=Side.parse(args.side),
        pov_rate=args.pov_rate,
        max_participation_rate=args.max_participation,
        half_spread_bps=args.half_spread_bps,
        impact_coefficient_bps=args.impact_bps,
        fee_per_share=args.fee_per_share,
    )
    dataset = load_dataset(args.data)
    results = run_backtest(dataset, config)
    write_results(results, dataset, config, args.results)
    _print_results(results)
    print(f"\nDetailed summary written to {args.results}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
