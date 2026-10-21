import numpy as np
from optics import OpticsConfig, lens_coordinates


def test_mesh_coordinates_and_limits():
    cfg = OpticsConfig(lens_count=4, segments_per_lens=16)
    vertices, faces = lens_coordinates(cfg)
    assert len(vertices) == 4 * (4 * 16 + 1)
    assert faces.shape[1] == 3
    assert np.isclose(vertices[:, 2].max(), 0.0)
    assert np.isclose(vertices[:, 2].min(), -0.002)
    assert np.isfinite(vertices).all()


def test_invalid_radius_rejected():
    try:
        lens_coordinates(OpticsConfig(radius_mm=0.2))
    except ValueError:
        pass
    else:
        raise AssertionError("Expected geometry validation failure")
