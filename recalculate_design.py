"""Recalculate paraxial geometry; no fitted crosstalk or FWHM claims.

Run: python recalculate_design.py
Coordinates and optical surfaces follow simulate.py / optics.py.
"""
import csv
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def geometry(data, distance=None, screen=None, rear_acrylic_mm=None):
    o = data['optics']
    n, t, p = o['ior'], o['thickness_mm'], o['pitch_mm']
    d = data['led_to_vertex_mm'] if distance is None else distance
    s = data['screen_from_vertex_mm'] if screen is None else screen
    if rear_acrylic_mm is None:
        rear_acrylic_mm = data.get('rear_acrylic_mm', 0.)
    nx = 1 / math.sqrt(1 + o['normal_slope'] ** 2)
    # PMMA flat entrance -> curved exit -> air groove -> planar PMMA.
    # Vertex/axis approximation; finite groove sag and aberrations are excluded.
    a = d - t + t/n - rear_acrylic_mm*(1-1/n)
    q = s / (n if data['screen_medium'] == 'pmma' else 1)
    pitch_h = o['led_pitch_horizontal_mm']
    period_h = p*(1+q/a)/nx
    step_h = q/a*pitch_h
    power = (n-1)/o['radius_mm']
    defocus = abs(1+q/a-q*power)
    source_width_h = q/a*o['led_width_horizontal_mm']
    # Full geometrical support of independent rectangular source and pupil.
    # Neither FWHM nor an aberration-inclusive width.
    widths = {}
    for name, fraction in [('unmasked', 1.), ('masked', data['mask']['open_fraction'])]:
        widths[name+'_support_horizontal_mm'] = source_width_h + p*fraction*defocus/nx
    return dict(led_to_vertex_mm=d, screen_from_vertex_mm=s, rear_acrylic_mm=rear_acrylic_mm,
                led_pitch_horizontal_mm=pitch_h, reduced_object_mm=a,
                reduced_screen_mm=q, stripe_period_horizontal_mm=period_h,
                target_phase_step_horizontal_mm=period_h/4,
                phase_step_horizontal_mm=step_h,
                four_step_error_horizontal_mm=4*step_h-period_h,
                relative_step_error_percent=100*(4*step_h/period_h-1), **widths)


def main():
    data = json.loads((ROOT/'configs/current.json').read_text(encoding='utf-8'))
    out = ROOT/'design_recalculated'
    out.mkdir(exist_ok=True)
    o = data['optics']
    nx = 1/math.sqrt(1+o['normal_slope']**2)
    normal = o['led_pitch_horizontal_mm']*nx
    n, t, p = o['ior'], o['thickness_mm'], o['pitch_mm']
    rear = data.get('rear_acrylic_mm', 0.)
    correction = rear*(1-1/n)
    a = data['led_to_vertex_mm']-t+t/n-correction
    factor = 4*normal/p-1
    q = data['screen_from_vertex_mm']/n
    matched_distance = q*factor+t-t/n+correction
    matched_screen = n*a/factor
    focus_screen = n/( (n-1)/o['radius_mm'] - 1/a )
    rows = [geometry(data, screen=round(1.3+.1*i, 1)) for i in range(8)]
    with (out/'screen_sweep.csv').open('w', newline='', encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
    distances=[geometry(data,distance=d) for d in (120.,125.,data['led_to_vertex_mm'],matched_distance)]
    with (out/'distance_sweep.csv').open('w', newline='', encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=distances[0].keys());w.writeheader();w.writerows(distances)
    h=data['baffles']['height_mm']; wall=data['baffles']['thickness_mm']
    width_normal=o['led_width_horizontal_mm']*nx
    clear_half=(normal-wall)/2
    # Conservative straight-ray condition: source far edge to same-phase
    # midpoint on the lens vertex plane. Ignores entrance refraction.
    h_point=data['led_to_vertex_mm']*clear_half/(2*normal)
    h_extended=data['led_to_vertex_mm']*(clear_half+width_normal/2)/(2*normal+width_normal/2)
    result=dict(
        assumptions='Paraxial geometric estimates, not measured crosstalk or FWHM. '
                    'Same-index contacted rear PMMA; post-lens PMMA; lens thickness 2mm.',
        rear_acrylic_mm=rear,
        corrected_led_pitch_normal_mm=normal,
        corrected_led_pitch_horizontal_mm=o['led_pitch_horizontal_mm'],
        same_phase_horizontal_mm=4*o['led_pitch_horizontal_mm'],
        current=geometry(data), screen_sweep=rows, distance_sweep=distances,
        matched_distance_at_current_screen_mm=matched_distance,
        matched_screen_at_current_distance_mm=matched_screen,
        paraxial_focus_screen_at_current_distance_mm=focus_screen,
        lens_air_effective_focal_length_from_radius_mm=o['radius_mm']/(n-1),
        user_reported_air_focal_length_mm=1.023,
        baffle_height_mm=h, baffle_thickness_normal_mm=wall,
        baffle_center_acceptance_half_angle_deg=math.degrees(math.atan(clear_half/h)),
        baffle_point_source_midpoint_block_height_mm=h_point,
        baffle_extended_source_midpoint_block_height_mm=h_extended,
        baffle_note='Geometric midpoint clipping only; not proof of no leakage, '
                    'scatter, image overlap or minimum crosstalk.')
    (out/'summary.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2,ensure_ascii=False))


if __name__ == '__main__':
    main()
