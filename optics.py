"""Mitsuba scene helpers. Geometry stored in meters; configuration in millimeters."""
from dataclasses import dataclass
import math
import numpy as np

MM = 1e-3


@dataclass(frozen=True)
class OpticsConfig:
    pitch_mm: float = 0.700
    radius_mm: float = 0.500
    thickness_mm: float = 2.0
    ior: float = 1.490
    led_to_flat_mm: float = 123.0
    led_width_horizontal_mm: float = 3.0
    led_pitch_horizontal_mm: float = 22.5
    lcd_distance_mm: float = 6.5
    normal_slope: float = 1.0 / 3.0
    lens_count: int = 40
    segments_per_lens: int = 64
    v_length_mm: float = 18.0
    receiver_width_mm: float = 8.0
    receiver_height_mm: float = 8.0
    emitter_radiance: float = 1.0
    led_count_each_side: int = 4

    def validate(self):
        if self.pitch_mm <= 0 or self.radius_mm < self.pitch_mm / 2:
            raise ValueError("Require positive pitch and radius >= half pitch")
        if self.thickness_mm <= self.radius_mm:
            raise ValueError("PMMA thickness must exceed curvature radius")
        if self.segments_per_lens < 4 or self.lens_count < 2:
            raise ValueError("Insufficient lens sampling")
        if self.led_width_horizontal_mm <= 0 or self.led_pitch_horizontal_mm <= 0:
            raise ValueError("Invalid LED dimensions")
        if self.receiver_width_mm <= 0 or self.receiver_height_mm <= 0:
            raise ValueError("Invalid receiver dimensions")


def lens_coordinates(cfg):
    """Closed watertight prism with repeating circular grooves (u,v coordinates).

    Winding on upper surface points toward +z; bottom toward -z.
    Returns vertices and triangular faces, with coordinates in meters.
    """
    cfg.validate()
    n = cfg.lens_count * cfg.segments_per_lens
    u = np.linspace(-cfg.lens_count * cfg.pitch_mm / 2,
                    cfg.lens_count * cfg.pitch_mm / 2, n + 1)
    offset = (u + cfg.pitch_mm / 2) % cfg.pitch_mm - cfg.pitch_mm / 2
    # Keep endpoints at seam; their heights match the neighboring grooves.
    top_z = -cfg.radius_mm + np.sqrt(
        np.maximum(0.0, cfg.radius_mm ** 2 - offset ** 2))
    theta = math.atan(cfg.normal_slope)
    normal = np.array([math.cos(theta), math.sin(theta)])
    tangent = np.array([-math.sin(theta), math.cos(theta)])
    v_edges = [-cfg.v_length_mm / 2, cfg.v_length_mm / 2]
    verts = []
    for z_layer in (0, 1):  # top, bottom
        for v in v_edges:
            for k, uk in enumerate(u):
                xy = normal * uk + tangent * v
                z = top_z[k] if z_layer == 0 else -cfg.thickness_mm
                verts.append([xy[0] * MM, xy[1] * MM, z * MM])
    stride = n + 1
    a, b, c, d = 0, stride, 2 * stride, 3 * stride
    faces = []
    for k in range(n):
        # outward upper normal +z
        faces += [[a+k, a+k+1, b+k+1], [a+k, b+k+1, b+k]]
        # outward lower normal -z
        faces += [[c+k, d+k+1, c+k+1], [c+k, d+k, d+k+1]]
    # left and right end caps
    faces += [[a, b, d], [a, d, c]]
    faces += [[a+n, d+n, b+n], [a+n, c+n, d+n]]
    # front and rear lateral walls
    for k in range(n):
        faces += [[a+k, c+k+1, a+k+1], [a+k, c+k, c+k+1]]
        faces += [[b+k, b+k+1, d+k+1], [b+k, d+k+1, d+k]]
    return np.asarray(verts, dtype=np.float32), np.asarray(faces, dtype=np.int32)


def make_scene(cfg, phase, lens_ply, spp=128):
    """Single averaged irradiance sensor. Not a spatial irradiance map."""
    if phase not in range(4):
        raise ValueError("phase must be 0..3")
    if spp < 1:
        raise ValueError("spp must be >= 1")
    import mitsuba as mi
    T = mi.ScalarTransform4f
    angle = math.atan(cfg.normal_slope)
    nx = math.cos(angle)
    scene = {
        "type": "scene",
        "integrator": {"type": "path", "max_depth": 12},
        "lens": {
            "type": "ply", "filename": str(lens_ply), "face_normals": True,
            "bsdf": {"type": "dielectric", "int_ior": cfg.ior, "ext_ior": 1.0},
        },
        "receiver": {
            "type": "rectangle",
            # Normal faces LED (-z). Rectangle local coordinates are [-1,1].
            "to_world": T.translate([0, 0, cfg.lcd_distance_mm * MM])
                @ T.rotate([1, 0, 0], 180)
                @ T.scale([cfg.receiver_width_mm * MM / 2,
                           cfg.receiver_height_mm * MM / 2, 1]),
            "sensor": {
                "type": "irradiancemeter",
                "film": {"type": "hdrfilm", "width": 1, "height": 1,
                         "pixel_format": "luminance",
                         "rfilter": {"type": "box"}},
                "sampler": {"type": "independent", "sample_count": spp},
            },
        }
    }
    for i in range(-cfg.led_count_each_side, cfg.led_count_each_side + 1):
        if i % 4 != phase:
            continue
        # Original Unity uses horizontal LED pitch and width, projected to
        # the direction normal to grooves. Here LEDs are extended in v.
        u_mm = i * cfg.led_pitch_horizontal_mm * nx
        width_u_mm = cfg.led_width_horizontal_mm * nx
        xy = [math.cos(angle) * u_mm, math.sin(angle) * u_mm]
        scene[f"led_{i+cfg.led_count_each_side}"] = {
            "type": "rectangle",
            "to_world": T.translate([xy[0] * MM, xy[1] * MM,
                                    -(cfg.led_to_flat_mm + cfg.thickness_mm) * MM])
                @ T.rotate([0, 0, 1], math.degrees(angle))
                @ T.scale([width_u_mm * MM / 2, cfg.v_length_mm * MM / 2, 1]),
            "emitter": {"type": "area", "radiance": cfg.emitter_radiance},
        }
    return scene
