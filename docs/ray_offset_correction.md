# Ray offset correction (2026-11-20)

The earlier metre-coordinate scene was numerically too small for Mitsuba's ray-origin offsets. Direct scalar_rgb ray intersection/BSDF traces reproduced a ~0.089 mm origin displacement at the curved lens surface. The air gap to the flat front acrylic is only ~0.0036–0.0146 mm at lens-normal coordinates u=0.06–0.12 mm. Rays could therefore skip an interface. A reverse trace from inside the front acrylic skipped the lens curve and reached the rear flat face. This is a correctness defect, not evidence of physical lens blur.

`simulate.load_config` now records `render.scene_scale=1000` by default. All shape transforms, camera translations and clip distances are consistently rescaled; camera rotations and field of view stay unchanged. Scan camera updates use the same scale. Configured physical dimensions remain in millimetres. Changing this value alters numerical coordinates, not the physical optical design. Set it to 1 only to reproduce the defective old scene. Existing scan resumes are rejected when settings lack the new scale metadata.

The regression test `tests/test_scene_scale.py` reproduces the skipped curved interface at scale 1 and requires the proper acrylic -> lens curve -> lens rear sequence at scale 1000. This verifies representative rays, not convergence of the complete caustic or every grazing ray. Further scale/sampling checks remain necessary.

Do not use prior width (~0.29 mm), illumination-overlap metrics, projected-eye metrics (~25%), or the derived acrylic-gap recommendation (~7 mm) as verified physical conclusions. They were based on the affected fields and require recalculation after this fix.

For the next small GPU diagnostic:

```powershell
git pull
.\.venv\Scripts\python.exe single_led_diagnostic.py --led-length-mm 10
```

The same 2 jobs are run, with all baffles and physical distances preserved. GPU/Windows execution of this correction has not been verified here. No full display scan is needed before checking the local result.
