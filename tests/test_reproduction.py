"""Tests for the Unity-style postprocessing (no Mitsuba installation required)."""
import numpy as np

from reproduce_unity import (
    blur_for_lcd, diffuser_sigma_mm, measure_profile, phase_comparison,
)


def test_diffuser_matches_unity_formula():
    assert diffuser_sigma_mm(6.5, 1.0) == 0
    assert np.isclose(
        diffuser_sigma_mm(1.029, 1.0) * 2.354820045,
        2 * (6.5 - 1.029) * np.tan(np.deg2rad(0.5)),
        rtol=1e-9,
    )


def test_profile_period_and_centers():
    x = (np.arange(16384) + 0.5) * 8 / 16384
    width = 0.10
    profiles = []
    for phase in range(4):
        periodic = ((x - phase * 0.175 + 0.35) % 0.7) - 0.35
        y = np.exp(-0.5 * (periodic / width) ** 2)
        m = measure_profile(y, 8.0)
        assert m["valid"]
        assert 0.55 <= m["period_mm"] <= 0.90
        assert m["contrast"] > 0.8
        profiles.append(m)
    steps = phase_comparison(profiles)
    assert steps["valid"]
    assert all(abs(s) < 0.25 for s in steps["signed_steps_mm"])


def test_blur_preserves_uniform_image():
    a = np.ones((21, 33), dtype=float)
    b = blur_for_lcd(a, 0.1, 8, 8)
    assert np.allclose(a, b)


def test_empty_profile_is_not_measured():
    assert not measure_profile(np.zeros(1024), 8.0)["valid"]
