# Mitsuba 3 Lenticular Irradiance Research

Mitsuba 3-only research prototype for LED → PMMA lenticular lens → LCD-plane irradiance.

## Status
**Stage 1 (initial prototype):** closed lenticular PMMA mesh, Lambertian LED area emitter(s), and a single Mitsuba `irradiancemeter` patch at the LCD plane. This yields **mean irradiance on one patch**, not yet a 1920×1080 irradiance map. No accuracy or runtime performance is asserted until verified against the original Unity code and convergence tests.

## Geometry (all configuration values in mm)
- Convex lens vertex: z = 0
- Flat PMMA entrance face: z = -2.0
- LED plane: z = -125.0 (123 mm behind the flat face)
- LCD plane: z = +6.5
- Pitch 0.700; cylindrical radius 0.500; PMMA refractive index 1.490
- LED horizontal width 3.0; horizontal center pitch 22.5
- Grooves tilted with normal in panel plane (1, 1/3), corresponding to slope 1:3
- Four phases: one of each four bars illuminates, represented by index i % 4.

Mitsuba scene coordinates are in **meters** (configuration and printed measurements remain in mm).

## Setup
Requires Python 3.10+ and Mitsuba 3 with a supported rendering backend. GPU CUDA is optional.

```bash
python -m pip install -r requirements.txt
python run.py --phase 0 --spp 128 --variant llvm_ad_rgb
```

Results: `results/phase_0.json` and an optional `results/phase_0.exr`. The EXR is a **1×1 meter reading of the receiving patch**. It is *not* an image of the LCD plane.

## Scientific caveats
- A single 1×1 `irradiancemeter` reports average irradiance of its attached rectangle. It does not sample a spatial map.
- Standard path tracing can struggle with refractive caustics. The output is diagnostic only until sample convergence and sensor compatibility are tested.
- The finite solid mesh represents a cropped lens array; edge effects are present.
- The baseline scene uses one or more idealized Lambertian rectangular LED emitters, not measured LED intensity distributions.
- Absolute irradiance requires known emitter radiance / source power calibration. Here values are preliminary simulation units.
- Phase comparison must keep geometry and sources within common spatial boundaries.

## Next milestones
1. Verify `irradiancemeter` output and convergence with a no-lens reference.
2. Validate PMMA lens mesh normals, units, and Fresnel refraction.
3. Implement a **calibrated spatial irradiance receiver** with appropriate transport sampling, instead of treating a rendered RGB image as irradiance.
4. Add high-resolution 8 mm / 16,384-sample profile, FWHM/period/contrast, and 4-phase comparison.
5. Add rough surfaces, measured source profiles, scattering, and manufacturing errors only after baseline validation.

This repository is independent of the legacy Unity application.


## Unity reproduction workflow (Mitsuba renderer)

Run the new spatial-render pipeline:

```bash
python -m pip install -r requirements.txt
python reproduce_unity.py --variant llvm_ad_rgb --spp 1024 --screen-mm 1.029
```

Four phase outputs are written to `results/`: `phase_0_irradiance.npy` through `phase_3_irradiance.npy`, four profile CSV files, `metrics.json` and `overview.png`.

The default is a **cropped 8×8 mm** optical test at 640×360 pixels, not the full LCD. To request full LCD dimensions (528×297 mm), use:

```bash
python reproduce_unity.py --full-panel --width 1920 --height 1080 --spp 4096
```

This full-scale Monte Carlo calculation may be extremely slow. It is **not a real-time 4-phase GUI**. The original Unity implementation uses a deterministic Compute Shader and is fundamentally different from the Mitsuba `ptracer` workflow.

### Unity feature mapping

| Unity feature | Mitsuba reproduction | Fidelity |
|---|---|---|
| PMMA cylindrical grooves (pitch 0.7 mm, R 0.5 mm) | Periodic triangle-mesh dielectric | Approximate; mesh resolution test required |
| 123 mm LED–flat-PMMA separation | LED rectangles at z = -125 mm | Geometrically matched |
| LED 3 mm width / 22.5 mm horizontal pitch | Rotated emitter rectangles | Geometrically matched |
| 4 phases | Separate Mitsuba renders for each LED group | Implemented |
| Virtual screen at distance 0.25–10 mm | Lambertian receiver at `--screen-mm` (currently 0.25–6.5) | Limited interval |
| White diffuser | Gaussian blur with the Unity angular FWHM formula | Approximation, not actual scattering |
| Image 1920×1080 | `--full-panel --width 1920 --height 1080` | Experimental and expensive |
| High-res 8 mm/16,384 point profile | CSV of interpolated render line | **Not equivalent** to Unity's independent 16,384-point ray integration |
| Period/FWHM/contrast/phase centers | `metrics.json` | Unity-inspired analysis; convergence not verified |
| Continuous slider and 0.5 s phase animation | Command-line batch | **Not implemented** |
| Real LCD plane measurement | Virtual receiver + optional Gaussian angular-spread model | Not calibrated irradiance sensor |

### Critical scientific limitations

- The visible irradiance field is estimated from radiance reflected by a **unit-Lambertian screen**, multiplied by π, under linear HDR assumptions. Validate normalization with a reference scene before treating values as absolute W/m².
- The scene uses Mitsuba's particle tracer to resolve lens caustics; the result can have substantial Monte Carlo noise. Increase `--spp` and confirm convergence.
- The Unity deterministic solver integrates apertures differently. Agreement should be assessed only after matching source geometry, boundaries, optical interfaces, direct and indirect paths, and measurement plane.
- In this initial reimplementation, the diffuser is *not* a scattering BSDF and no real manufactured lens error or measured source profiles are supplied.
- `reproduce_unity.py` is a newly committed implementation which has **not yet been executed with a Mitsuba installation**; compatibility and output must be checked on a machine with Mitsuba installed.
- No claim of physical or pixel-level equivalence with Unity is made yet.
