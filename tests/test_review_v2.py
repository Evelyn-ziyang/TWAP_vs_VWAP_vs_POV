from __future__ import annotations

import math

from figures.generate_readme_figures import ORDER_FRACTION, rolling_window_observations


def test_review_v2_dynamic_q_windows_are_normalized_and_complete() -> None:
    observations = rolling_window_observations()

    assert len(observations) == 115
    assert {observation.session for observation in observations} == {
        "2026-07-27",
        "2026-07-28",
        "2026-07-29",
        "2026-07-30",
        "2026-07-31",
    }
    for observation in observations:
        assert observation.target_qty == max(1, math.floor(observation.volume * ORDER_FRACTION))
        assert observation.twap_fill == 1.0
        assert observation.vwap_fill == 1.0
        assert observation.pov_fill == 1.0
