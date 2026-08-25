from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from pathlib import Path

import pytest

from algo_exec import (
    ExecutionConfig,
    Side,
    allocate_integer,
    build_volume_profile,
    load_dataset,
    pov,
    run_backtest,
    simulate_execution,
    split_train_test,
    twap,
    vwap,
)


ROOT = Path(__file__).resolve().parents[1]


def make_bar(stamp: datetime, volume: float, price: float = 100.0) -> dict[str, object]:
    return {
        "timestamp": stamp.isoformat(),
        "open": price,
        "high": price + 1.0,
        "low": price - 1.0,
        "close": price + 0.25,
        "volume": volume,
    }


def test_twap_uses_integer_largest_remainder_and_preserves_quantity() -> None:
    assert twap(10, 3) == [4, 3, 3]
    assert twap(12, 3, lot_size=2) == [4, 4, 4]
    assert sum(allocate_integer(1_003, [0.2, 0.3, 0.5])) == 1_003


def test_vwap_is_weighted_and_rejects_bad_profiles() -> None:
    assert vwap(100, [1, 3]) == [25, 75]
    assert vwap(2, [1, 1, 1]) == [1, 1, 0]
    for bad_profile in ([], [0, 0], [-1, 3], [1, math.nan], [1, math.inf], [1e308, 1e308]):
        with pytest.raises(ValueError):
            vwap(100, bad_profile)


def test_schedule_input_validation() -> None:
    with pytest.raises(ValueError):
        twap(-1, 3)
    with pytest.raises(ValueError):
        twap(100, 0)
    with pytest.raises(ValueError):
        twap(101, 3, lot_size=10)
    with pytest.raises(ValueError):
        pov(100, [100], 0)
    with pytest.raises(ValueError):
        pov(100, [math.nan], 0.1)
    with pytest.raises(ValueError):
        ExecutionConfig(total_qty=0).validated()


def test_pov_respects_volume_cap_and_can_leave_residual() -> None:
    assert pov(100, [100, 50], 0.10) == [10, 5]
    assert pov(150, [1_000, 1_000, 1_000], 0.10) == [100, 50, 0]
    schedule = pov(1_000, [101, 202, 303], 0.10)
    assert all(qty <= math.floor(volume * 0.10) for qty, volume in zip(schedule, [101, 202, 303]))
    assert sum(schedule) < 1_000


def test_volume_profile_is_median_of_daily_normalized_shares() -> None:
    first = datetime(2026, 7, 27, 13, 30, tzinfo=timezone.utc)
    second = first + timedelta(days=1)
    target_day = first + timedelta(days=2)
    training = [
        make_bar(first, 10),
        make_bar(first + timedelta(minutes=5), 30),
        make_bar(second, 20),
        make_bar(second + timedelta(minutes=5), 20),
    ]
    target = [make_bar(target_day, 1), make_bar(target_day + timedelta(minutes=5), 1)]
    profile = build_volume_profile(training, target)
    assert profile == pytest.approx([0.375, 0.625])
    assert sum(profile) == pytest.approx(1.0)


def test_fill_model_is_side_aware_and_rolls_liquidity_forward() -> None:
    start = datetime(2026, 7, 31, 13, 30, tzinfo=timezone.utc)
    bars = [make_bar(start, 100), make_bar(start + timedelta(minutes=5), 1_000)]
    buy_config = ExecutionConfig(total_qty=100, side=Side.BUY, max_participation_rate=0.10)
    buy = simulate_execution("TWAP", [100, 0], bars, buy_config)
    assert buy.executed_qty == 100
    assert [fill.qty for fill in buy.fills] == [10, 90]
    assert all(fill.fill_price > fill.reference_price for fill in buy.fills)

    sell_config = ExecutionConfig(total_qty=100, side=Side.SELL, max_participation_rate=0.10)
    sell = simulate_execution("TWAP", [100, 0], bars, sell_config)
    assert all(fill.fill_price < fill.reference_price for fill in sell.fills)
    assert buy.total_modelled_cost > 0
    assert sell.total_modelled_cost > 0


def test_bundled_data_runs_all_algorithms_out_of_sample() -> None:
    dataset = load_dataset(ROOT / "Data_example" / "example.pkl")
    train, test = split_train_test(dataset["records"])
    assert len({row["session"] for row in train}) == 5
    assert len(test) == 78
    assert {row["session"] for row in test} == {"2026-07-31"}

    results = run_backtest(dataset, ExecutionConfig())
    assert set(results) == {"TWAP", "VWAP", "POV"}
    for result in results.values():
        assert result.executed_qty + result.remaining_qty == result.requested_qty
        assert sum(fill.qty for fill in result.fills) == result.executed_qty
        assert math.isfinite(result.vwap_slippage_bps)
        assert result.total_modelled_cost > 0
