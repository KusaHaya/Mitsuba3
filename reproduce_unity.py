"""Mitsuba 3 reproduction workflow for the Unity lenticular simulator.

This is a physically-rendered *comparison implementation*, not a numerical
identity with Unity's deterministic direct-ray Compute Shader. Unlike the
earlier 1x1 irradiance meter this script produces a spatial image by measuring
radiance from a unit-reflectance Lambertian receiver and multiplying by pi.
The conversion assumes this ideal BSDF and linear HDR output.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
import math
from pathlib import Path

import numpy as np
from optics import OpticsConfig, lens_coordinates
from run import write_binary_ply

PANEL_WIDTH = 528.0
PANEL_HEIGHT = 297.0
LCD_Z = 6.5


def scene_for_phase(mi, cfg, phase, mesh_path, width_mm, height_mm,
                    resolution, sample_count, receive_distance_mm):
    T = mi.ScalarTransform4f
    # Camera views the LED-facing side of a white screen. Orthographic sensor
    # does NOT pass through the lens (the receiver sits in front of it).
    sensor_z = receive_distance_mm - 0.1
    scene = {
        "type": "scene",
        "integrator": {
            "type": "ptracer", "max_depth": 12,
            "samples_per_pass": min(256, sample_count),
            "hide_emitters": True,
        },
        "lens": {
            "type": "ply", "filename": str(mesh_path), "face_normals": True,
            "bsdf": {
                "type": "dielectric",
                "int_ior": cfg.ior,
                "ext_ior": 1.0
            },
        },
        "lcd_receiver": {
            "type": "rectangle",
            "to_world": (
                T.translate([0, 0, receive_distance_mm * 0.001])
                @ T.rotate([1, 0, 0], 180)
                @ T.scale([width_mm * 0.0005, height_mm * 0.0005, 1])
            ),
            "bsdf": {
                "type": "diffuse", "reflectance": {
                    "type": "rgb", "value": [1.0, 1.0, 1.0]
                }
            },
        },
        "sensor": {
            "type": "orthographic",
            "to_world": (
                T.look_at(
                    origin=[0, 0, sensor_z * 0.001],
                    target=[0, 0, receive_distance_mm * 0.001],
                    up=[0, 1, 0]
                )
                @ T.scale([width_mm * 0.0005, height_mm * 0.0005, 1])
            ),
            "near_clip": 1e-6,
            "far_clip": 1.0,
            "film": {
                "type": "hdrfilm", "width": resolution[0],
                "height": resolution[1], "pixel_format": "rgb",
                "component_format": "float32",
                "rfilter": {"type": "box"}
            },
            "sampler": {"type": "independent", "sample_count": sample_count}
        }
    }
    angle = math.atan(cfg.normal_slope)
    nx = math.cos(angle)
    for i in range(-cfg.led_count_each_side, cfg.led_count_each_side + 1):
        if i % 4 != phase:
            continue
        u_mm = i * cfg.led_pitch_horizontal_mm * nx
        xy = [math.cos(angle) * u_mm, math.sin(angle) * u_mm]
        scene[f"led_{i+cfg.led_count_each_side}"] = {
            "type": "rectangle",
            "to_world": (
                T.translate([xy[0] * 0.001, xy[1] * 0.001,
                    -(cfg.led_to_flat_mm + cfg.thickness_mm) * 0.001])
                @ T.rotate([0, 0, 1], math.degrees(angle))
                @ T.scale([cfg.led_width_horizontal_mm * nx * 0.0005,
                           cfg.v_length_mm * 0.0005, 1])
            ),
            "emitter": {"type": "area", "radiance": cfg.emitter_radiance}
        }
    return mi.load_dict(scene)


def diffuser_sigma_mm(distance_mm, angle_fwhm_deg, lcd_z=LCD_Z):
    distance = max(0.0, lcd_z - distance_mm)
    fwhm = 2.0 * distance * math.tan(math.radians(angle_fwhm_deg / 2.0))
    return fwhm / 2.354820045


def blur_for_lcd(image, sigma_mm, width_mm, height_mm):
    if sigma_mm <= 0:
        return image
    from scipy.ndimage import gaussian_filter
    sy = sigma_mm / (height_mm / image.shape[0])
    sx = sigma_mm / (width_mm / image.shape[1])
    return gaussian_filter(image, sigma=(sy, sx), mode="nearest")


def measure_profile(profile, span_mm):
    """Unity-inspired periodic-envelope metrics, applied to noisy Mitsuba data.

    Reject invalid/insufficiently sampled profiles instead of inventing peaks.
    """
    y = np.asarray(profile, dtype=np.float64)
    if len(y) < 64 or not np.isfinite(y).all() or np.max(y) <= 0:
        return {"valid": False, "reason": "empty or invalid profile"}
    dx = span_mm / len(y)
    # Lag constrained to match Unity's 0.55..0.90 mm macro-period.
    y0 = y - y.mean()
    down = max(1, len(y) // 4096)
    yy = y0[::down]
    d = dx * down
    lo, hi = max(1, math.ceil(0.55 / d)), math.floor(0.90 / d)
    if hi <= lo or len(yy) <= hi:
        return {"valid": False, "reason": "insufficient profile resolution"}
    correlations = [
        float(np.dot(yy[:-lag], yy[lag:]) /
            max(np.linalg.norm(yy[:-lag])*np.linalg.norm(yy[lag:]), 1e-30))
        for lag in range(lo, hi + 1)
    ]
    period = (lo + int(np.argmax(correlations))) * d
    bins = 1024
    x = (np.arange(len(y)) + 0.5) * dx
    index = np.minimum(((x % period) / period * bins).astype(int), bins-1)
    sums = np.bincount(index, weights=y, minlength=bins)
    counts = np.bincount(index, minlength=bins)
    folded = sums / np.maximum(counts, 1)
    peak = int(np.argmax(folded))
    floor, maximum = float(np.min(folded)), float(np.max(folded))
    contrast = (maximum-floor) / max(maximum+floor, 1e-30)
    threshold = floor + (maximum-floor)*0.5
    allowed_gap = max(1, round(0.10 / (period / bins)))
    def extent(direction):
        last, gap = 0, 0
        for step in range(1, bins//2):
            idx = (peak+direction*step) % bins
            if folded[idx] >= threshold:
                last, gap = step, 0
            else:
                gap += 1
                if gap > allowed_gap:
                    break
        return last
    left, right = extent(-1), extent(+1)
    center = ((peak + 0.5 + (right-left)*0.5) / bins * period) % period
    return {
        "valid": True,
        "period_mm": period, "fwhm_mm": min(bins, left+right+1)*period/bins,
        "phase_center_mm": center, "contrast": contrast,
        "fwhm_over_period": min(bins, left+right+1)/bins,
        "peak_relative": maximum
    }


def phase_comparison(metrics):
    if any(not m.get("valid") for m in metrics):
        return {"valid": False, "reason": "one or more profiles invalid"}
    period = float(np.mean([m["period_mm"] for m in metrics]))
    centers = [m["phase_center_mm"] for m in metrics]
    steps = [
        ((centers[(i+1)%4]-centers[i]+period/2) % period) - period/2
        for i in range(4)
    ]
    target = period/4
    mean = float(np.mean(np.abs(steps)))
    subpixel = PANEL_WIDTH/1920/3
    return {
        "valid": True, "period_mm": period,
        "centers_mm": centers, "signed_steps_mm": steps,
        "step_sizes_subpixels": [abs(s)/subpixel for s in steps],
        "ideal_step_mm": target,
        "mean_step_mm": mean,
        "mean_step_error_mm": mean-target,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", default="llvm_ad_rgb")
    parser.add_argument("--spp", type=int, default=1024)
    parser.add_argument("--screen-mm", type=float, default=1.029,
                        help="Lens vertex to virtual screen plane (0.25..6.5 mm)")
    parser.add_argument("--diffuser-deg", type=float, default=1.0,
                        help="Gaussian white diffuser FWHM 0..3 degrees")
    parser.add_argument("--no-diffuser", action="store_true")
    parser.add_argument("--full-panel", action="store_true")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=360)
    parser.add_argument("--lens-segments", type=int, default=32)
    parser.add_argument("--profile-count", type=int, default=16384)
    parser.add_argument("--output", type=Path, default=Path("results"))
    args = parser.parse_args()
    if args.spp <= 0 or args.width <= 0 or args.height <= 0 or args.profile_count < 64:
        parser.error("spp, width and height must be positive; profile-count >= 64")
    if not 0.25 <= args.screen_mm <= 6.5 or not 0 <= args.diffuser_deg <= 3:
        parser.error("screen-mm should be 0.25..6.5; diffuser-deg 0..3")
    args.output.mkdir(parents=True, exist_ok=True)
    width_mm, height_mm = (PANEL_WIDTH, PANEL_HEIGHT) if args.full_panel else (8.0, 8.0)
    # Cover target window with repeated grooves; keep enough LED strips to cover.
    required_u = width_mm*0.95 + height_mm*0.32
    lens_count = max(40, math.ceil(required_u / 0.7) + 16)
    led_each_side = max(4, math.ceil(width_mm / 22.5 / 2) + 4)
    cfg = replace(
        OpticsConfig(), lens_count=lens_count,
        segments_per_lens=args.lens_segments,
        v_length_mm=(height_mm + width_mm/3) * 1.2 + 10,
        led_count_each_side=led_each_side,
    )
    vertices, faces = lens_coordinates(cfg)
    mesh = args.output / "lenticular_reproduction.ply"
    write_binary_ply(mesh, vertices, faces)
    import mitsuba as mi
    mi.set_variant(args.variant)
    sigma = 0 if args.no_diffuser else diffuser_sigma_mm(
        args.screen_mm, args.diffuser_deg, cfg.lcd_distance_mm)
    metrics = []
    from scipy.ndimage import zoom
    for phase in range(4):
        scene = scene_for_phase(
            mi, cfg, phase, mesh, width_mm, height_mm,
            (args.width, args.height), args.spp, args.screen_mm)
        rgb = np.asarray(mi.render(scene, spp=args.spp)).astype(np.float64)
        # White diffuse sheet reflectance 1: E = pi * L for Lambertian receiver
        irradiance = np.maximum(0, np.mean(rgb[..., :3], axis=2) * math.pi)
        irradiance = blur_for_lcd(irradiance, sigma, width_mm, height_mm)
        np.save(args.output / f"phase_{phase}_irradiance.npy", irradiance)
        # Center horizontal 8 mm line, interpolated to high-resolution grid.
        profile_low = irradiance[irradiance.shape[0]//2]
        xs = (np.arange(args.width)+0.5)/args.width*width_mm-width_mm/2
        xp = (np.arange(args.profile_count)+0.5)/args.profile_count*8-4
        profile = np.interp(xp, xs, profile_low, left=0, right=0)
        np.savetxt(args.output / f"phase_{phase}_profile.csv", np.c_[xp,profile],
                   delimiter=",", header="x_mm,relative_irradiance", comments="")
        metric = measure_profile(profile, 8.0)
        metrics.append(metric)
        print(f"Phase {phase}: {metric}")
    comparison = phase_comparison(metrics)
    result = {
        "method": "Mitsuba 3 ptracer: illuminated virtual screen, optional Gaussian diffuser to LCD",
        "scientific_warning": (
            "Radiance-to-irradiance conversion assumes unit-Lambertian receiver. "
            The 16384 profile points are interpolated from rendered pixels, "
            "not independent high-resolution ray traces. "
            "Convergence and physical calibration have not been verified."
        ),
        "parameters": {
            "full_panel": args.full_panel, "width_mm": width_mm, "height_mm": height_mm,
            "resolution": [args.width,args.height], "spp": args.spp,
            "screen_distance_mm": args.screen_mm,
            "diffuser_fwhm_deg": args.diffuser_deg, "diffuser_sigma_mm": sigma,
            "lens_count": cfg.lens_count, "lens_segments": cfg.segments_per_lens,
        }, "per_phase": metrics, "four_phase_comparison": comparison,
    }
    (args.output/"metrics.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, axes = plt.subplots(2, 1, figsize=(12, 8))
        for p in range(4):
            img = np.load(args.output/f"phase_{p}_irradiance.npy")
            axes[0].plot([], [], label=f"Phase {p}")
            data = np.loadtxt(args.output/f"phase_{p}_profile.csv",
                              delimiter=",", skiprows=1)
            axes[1].plot(data[:,0], data[:,1], label=f"Phase {p}")
        axes[0].imshow(np.load(args.output/"phase_0_irradiance.npy"),
                       extent=[-width_mm/2,width_mm/2,-height_mm/2,height_mm/2],
                       origin="lower", aspect="auto")
        axes[0].set_title("Phase 0 LCD illumination (relative)")
        axes[1].set_title("Center line profiles")
        axes[1].set_xlabel("x (mm)")
        axes[1].legend()
        fig.tight_layout()
        fig.savefig(args.output/"overview.png", dpi=160)
        plt.close(fig)
    except ImportError:
        print("Matplotlib missing: CSV and NPY outputs are still available.")
    print(f"Saved results in {args.output}")


if __name__ == "__main__":
    main()
