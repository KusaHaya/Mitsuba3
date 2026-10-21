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
