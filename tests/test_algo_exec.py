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
        pov(100, [100], 0.1, lag_bars=-1)
    with pytest.raises(ValueError):
        ExecutionConfig(total_qty=0).validated()


def test_pov_respects_volume_cap_and_can_leave_residual() -> None:
    assert pov(100, [100, 50], 0.10) == [0, 10]
    assert pov(150, [1_000, 1_000, 1_000], 0.10) == [0, 100, 50]
    assert pov(100, [100, 50], 0.10, lag_bars=0) == [10, 5]
    schedule = pov(1_000, [101, 202, 303], 0.10)
    decision_volumes = [0, 101, 202]
    assert all(qty <= math.floor(volume * 0.10) for qty, volume in zip(schedule, decision_volumes))
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


def test_volume_profile_rejects_missing_slots_and_too_little_history() -> None:
    first = datetime(2026, 7, 27, 13, 30, tzinfo=timezone.utc)
    training = [make_bar(first, 10)]
    target = [make_bar(first + timedelta(days=1), 1)]
    with pytest.raises(ValueError, match="at least 2 training sessions"):
        build_volume_profile(training, target, min_training_sessions=2)

    target_with_extra_slot = [
        make_bar(first + timedelta(days=1), 1),
        make_bar(first + timedelta(days=1, minutes=5), 1),
    ]
    with pytest.raises(ValueError, match="missing target slots"):
        build_volume_profile(training, target_with_extra_slot)


def test_fill_metrics_separate_gross_price_and_fees_and_prefer_bar_vwap() -> None:
    start = datetime(2026, 7, 31, 13, 30, tzinfo=timezone.utc)
    bar = make_bar(start, 1_000, price=100.0)
    bar.update({"bar_vwap": 100.5, "half_spread_bps": 2.0, "fee_per_share": 0.01})
    result = simulate_execution(
        "TWAP",
        [100],
        [bar],
        ExecutionConfig(total_qty=100, impact_coefficient_bps=0.0),
    )
    assert result.fills[0].reference_price == pytest.approx(100.5)
    assert result.arrival_shortfall_bps > result.arrival_price_shortfall_bps
    assert result.vwap_slippage_bps > result.vwap_price_slippage_bps


def test_external_pickle_requires_explicit_trust(tmp_path: Path) -> None:
    external = tmp_path / "external.pkl"
    external.write_bytes((ROOT / "Data_example" / "example.pkl").read_bytes())
    with pytest.raises(ValueError, match="untrusted pickle"):
        load_dataset(external)
    trusted = load_dataset(external, allow_unsafe_pickle=True)
    assert trusted["records"]


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
