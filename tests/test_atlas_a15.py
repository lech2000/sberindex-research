"""A15 must detect transferable sector information and reject a null label."""

from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "economic-atlas/src"))
from a15_sector_construct_validity import region_cv


def sample(seed: int = 8) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    n_regions, each = 15, 20
    region = np.repeat(np.arange(n_regions), each)
    label = rng.integers(0, 5, len(region))
    log_pop = rng.normal(10, .7, len(region))
    lat = rng.normal(50, 2, n_regions)[region] + rng.normal(0, .2, len(region))
    lon = rng.normal(45, 3, n_regions)[region] + rng.normal(0, .2, len(region))
    frame = pd.DataFrame({"region": region.astype(str), "label": label.astype(str),
                          "type": rng.choice(["округ", "район"], len(region)),
                          "log_pop": log_pop, "log_pop_sq": log_pop**2,
                          "lat": lat, "lon": lon, "lat_sq": lat**2,
                          "lon_sq": lon**2, "lat_lon": lat * lon})
    signal = .45 * label + .01 * lat + rng.normal(0, .05, len(region))
    null = .04 * log_pop + .01 * lat + rng.normal(0, .1, len(region))
    return frame, signal, null


def test_region_held_out_check_distinguishes_transferable_signal_from_null():
    frame, signal, null = sample()
    positive, _ = region_cv(frame, signal)
    negative, _ = region_cv(frame, null)
    assert positive["mse_reduction"] > .5
    assert positive["ci95_region_bootstrap"][0] > 0
    assert positive["positive_folds"] == 5
    assert positive["strong_signal"]
    assert not negative["strong_signal"]
    assert negative["ci95_region_bootstrap"][0] < 0
