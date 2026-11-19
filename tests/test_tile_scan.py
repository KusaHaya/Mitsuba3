import copy
import json
from pathlib import Path
import numpy as np
import pytest
from simulate import load_config,scene_dict
from scan_tiles import make_tiles,tile_data,peak_stats,shape_overlap,valid_field

CONFIG=Path(__file__).resolve().parents[1]/'configs/current.json'


def test_bands_cover_equal_200mm_spans_without_gaps():
    d,c=load_config(CONFIG);tiles=make_tiles(d,['center','left','right'])
    assert len(tiles)==75
    span=200.
    for region in ['center','left','right']:
        row=sorted([t for t in tiles if t['region']==region],key=lambda t:t['index'])
        assert np.isclose(sum(t['size_mm'][0] for t in row),span)
        for left,right in zip(row,row[1:]):
            assert np.isclose(left['center_mm'][0]+left['size_mm'][0]/2,
                              right['center_mm'][0]-right['size_mm'][0]/2)
    assert abs(tiles[0]['center_mm'][0])<1e-12
    assert tiles[0]['size_mm'][0]/2048<.004
    for tile in tiles:
        assert tile['pixels'][0]/tile['pixels'][1] == tile['size_mm'][0]/tile['size_mm'][1]
        assert tile['size_mm'][0]/tile['pixels'][0] == tile['size_mm'][1]/tile['pixels'][1]


def test_view_moves_camera_only_and_preserves_full_receiver_and_sources(tmp_path):
    mi=pytest.importorskip('mitsuba');mi.set_variant('scalar_rgb')
    d,c=load_config(CONFIG);t=make_tiles(d,['left'],pixels=64,limit=1)[0];v=tile_data(d,t)
    local=tmp_path/'view.json';local.write_text(json.dumps(v));load_config(local)
    assert v['roi_mm']==d['roi_mm'] and v['led_array']==d['led_array']
    a=scene_dict(mi,d,c,tmp_path/'lens.ply',0,'baffles','preview')
    b=scene_dict(mi,v,c,tmp_path/'lens.ply',0,'baffles','preview')
    for key in ['receiver','pmma_after_lens','led_0','baffle_0']:
        assert np.allclose(np.array(a[key]['to_world'].matrix),np.array(b[key]['to_world'].matrix))
    assert not np.allclose(np.array(a['sensor']['to_world'].matrix),np.array(b['sensor']['to_world'].matrix))
    assert len([key for key in b if key.startswith('led_')])==5


def test_overlap_index_and_missing_data_are_not_crosstalk(tmp_path):
    a=np.array([1.,0,0,0]);b=np.array([0.,0,1.,0])
    assert shape_overlap(a,a)==1
    assert shape_overlap(a,b)==0
    assert shape_overlap(a*5,a)==1
    assert shape_overlap(a,np.zeros(4)) is None
    assert peak_stats(np.zeros(128),.7,1)['width_horizontal_mm'] is None
    p=tmp_path/'test.npy';p.write_bytes(b'incomplete')
    assert not valid_field(p,(2,2))
    np.save(p,np.zeros((2,2),np.float32));assert valid_field(p,(2,2))


def test_local_fold_handles_float_roundoff_at_period_boundary():
    from simulate import folded_profile
    span=4*24.771175004652306/25
    x,p,count=folded_profile(np.ones((16,64)),[span,span/4],1/3,.7052517409521255,128)
    assert len(p)==128 and count.sum()==16*64
    assert np.allclose(p[np.isfinite(p)],1)


def test_backward_estimator_lambertian_reference():
    mi=pytest.importorskip('mitsuba');mi.set_variant('llvm_ad_rgb')
    scene=mi.load_dict({'type':'scene','integrator':{'type':'path','max_depth':4},
        'environment':{'type':'constant','radiance':1.},
        'receiver':{'type':'rectangle','bsdf':{'type':'diffuse','reflectance':1.}},
        'sensor':{'type':'perspective','fov':30,
                  'to_world':mi.ScalarTransform4f.look_at(origin=[0,0,1],target=[0,0,0],up=[0,1,0]),
                  'film':{'type':'hdrfilm','width':8,'height':8,'pixel_format':'rgb'},
                  'sampler':{'type':'independent','sample_count':256}}})
    # Unit environment radiance -> E=pi for a unit diffuse plane, Lo=E/pi=1.
    image=np.asarray(mi.render(scene,spp=256,seed=4))
    assert np.isfinite(image).all()
    assert abs(float(image.mean())-1.)<.05
