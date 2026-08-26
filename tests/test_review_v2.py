from __future__ import annotations

import math

from figures.generate_readme_figures import (
    ORDER_FRACTION,
    PROFILE_LOOKBACK_SESSIONS,
    completion_sensitivity,
    rolling_window_observations,
)


def test_review_v2_dynamic_q_windows_use_fixed_history_and_normalized_q() -> None:
    observations = rolling_window_observations()

    assert len(observations) == 23
    assert {observation.session for observation in observations} == {"2026-07-31"}
    for observation in observations:
        assert observation.training_sessions == PROFILE_LOOKBACK_SESSIONS
        assert observation.target_qty == max(1, math.floor(observation.volume * ORDER_FRACTION))


def test_nonoverlapping_robustness_and_completion_sensitivity() -> None:
    observations = rolling_window_observations(step_bars=12)
    assert len(observations) == 6
    assert len({observation.start_slot for observation in observations}) == 6

    samples = completion_sensitivity(rolling_window_observations())
    assert sorted(samples) == [0.03, 0.05, 0.10, 0.15]
    assert all(len(sample) == 23 for sample in samples.values())
    assert any(observation.pov_fill < 1.0 for observation in samples[0.15])
