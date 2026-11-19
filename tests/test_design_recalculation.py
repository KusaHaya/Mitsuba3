import copy
import json
import math
from pathlib import Path

import pytest
from recalculate_design import geometry

CONFIG = Path(__file__).resolve().parents[1]/'configs/current.json'


def test_corrected_pitch_is_235_normal():
    d=json.loads(CONFIG.read_text())
    o=d['optics']
    assert o['led_pitch_horizontal_mm']/math.sqrt(1+o['normal_slope']**2) == pytest.approx(23.5)


def test_quarter_period_matching_in_either_distance():
    d=json.loads(CONFIG.read_text());o=d['optics'];n=o['ior'];t=o['thickness_mm']
    normal=o['led_pitch_horizontal_mm']/math.sqrt(1+o['normal_slope']**2)
    factor=4*normal/o['pitch_mm']-1
    correction=d.get('rear_acrylic_mm',0)*(1-1/n)
    distance=d['screen_from_vertex_mm']/n*factor+t-t/n+correction
    screen=n*(d['led_to_vertex_mm']-t+t/n-correction)/factor
    assert geometry(d,distance=distance)['relative_step_error_percent'] == pytest.approx(0,abs=1e-10)
    assert geometry(d,screen=screen)['relative_step_error_percent'] == pytest.approx(0,abs=1e-10)


def test_at_paraxial_focus_width_is_source_image_width():
    d=json.loads(CONFIG.read_text());o=d['optics'];n=o['ior'];t=o['thickness_mm']
    a=d['led_to_vertex_mm']-t+t/n-d.get('rear_acrylic_mm',0)*(1-1/n)
    s=n/((n-1)/o['radius_mm']-1/a)
    r=geometry(d,screen=s)
    expected=s/n/a*o['led_width_horizontal_mm']
    assert r['unmasked_support_horizontal_mm'] == pytest.approx(expected)
    assert r['masked_support_horizontal_mm'] == pytest.approx(expected)
