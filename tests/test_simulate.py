import copy
import json
from pathlib import Path
import math
import numpy as np
import pytest
from simulate import load_config, folded_profile, scene_dict, lens_mesh_config

CONFIG = Path(__file__).resolve().parents[1]/'configs/current.json'


def write_config(tmp_path, modify):
    data=json.loads(CONFIG.read_text(encoding='utf-8'))
    modify(data)
    p=tmp_path/'config.json';p.write_text(json.dumps(data))
    return p


def test_vertex_distance_and_screen_are_unambiguous():
    d,cfg=load_config(CONFIG)
    assert cfg.led_to_flat_mm==pytest.approx(136.13)
    assert cfg.led_to_flat_mm+cfg.thickness_mm==d['led_to_vertex_mm']==138.13
    assert d['screen_from_vertex_mm']==1.5


@pytest.mark.parametrize('modify',[
    lambda d:d.update(led_to_vertex_mm=1),
    lambda d:d['mask'].update(open_fraction=1.1),
    lambda d:d['baffles'].update(height_mm=999),
    lambda d:d['render']['preview'].update(height=128),
    lambda d:d['optics'].update(lens_count=3),
    lambda d:d['led_array'].update(count=9),
    lambda d:d.update(cases=[]),
    lambda d:d['optics'].update(normal_slope=float('nan')),
    lambda d:d.update(rear_acrylic_mm=-1),
    lambda d:d.update(rear_acrylic_mm=float('nan')),
    lambda d:d.update(rear_acrylic_mm=200),
    lambda d:d['baffles'].update(height_mm=130),
])
def test_invalid_physical_and_sampling_settings_rejected(tmp_path,modify):
    with pytest.raises(ValueError):load_config(write_config(tmp_path,modify))


def test_profile_respects_camera_orientation_and_preserves_missing_bins():
    n=256;span=8.;slope=1/3;period=.7
    x=span/2-(np.arange(n)+.5)*span/n
    X,Y=np.meshgrid(x,x);u=(X+slope*Y)/math.sqrt(1+slope*slope)
    im=2+np.cos(2*np.pi*(u-.2)/period)
    bins,profile,count=folded_profile(im,[span,span],slope,period,128)
    ideal=2+np.cos(2*np.pi*(bins-.2)/period)
    assert np.nanmax(abs(profile-ideal))<.03
    _,p,c=folded_profile(np.ones((2,2)),[span,span],slope,period,128)
    assert np.isnan(p[c==0]).all()  # Missing samples must not imply perfect dark regions.


def test_contacted_rear_plate_extends_only_flat_side_and_legacy_defaults_to_zero():
    from optics import lens_coordinates
    d,cfg=load_config(CONFIG)
    assert d['rear_acrylic_mm']==10
    mesh_cfg=lens_mesh_config(d,cfg)
    vertices,_=lens_coordinates(mesh_cfg)
    assert np.isclose(vertices[:,2].min(),-.012)
    assert np.isclose(vertices[:,2].max(),0)
    assert mesh_cfg.radius_mm==cfg.radius_mm and mesh_cfg.pitch_mm==cfg.pitch_mm
    legacy=dict(d);legacy.pop('rear_acrylic_mm')
    assert lens_mesh_config(legacy,cfg).thickness_mm==cfg.thickness_mm


def test_mitsuba_scene_and_actual_render(tmp_path):
    mi=pytest.importorskip('mitsuba')
    mi.set_variant('llvm_ad_rgb')
    from optics import lens_coordinates
    from run import write_binary_ply
    d,cfg=load_config(CONFIG);d=copy.deepcopy(d)
    d['render']['preview']={'width':32,'height':32,'spp':64}
    d['roi_mm']=[8,8]
    mesh=tmp_path/'lens.ply';v,f=lens_coordinates(lens_mesh_config(d,cfg));write_binary_ply(mesh,v,f)
    for case in ['baseline','mask','baffles','mask_baffles']:
        obj=scene_dict(mi,d,cfg,mesh,0,case,'preview')
        assert obj['sensor']['type']=='perspective'
        scene=mi.load_dict(obj)
        im=np.asarray(mi.render(scene,spp=64,seed=3))
        assert im.shape==(32,32,3)
        assert np.isfinite(im).all() and im.max()>0
    # Baffle origin and scale correspond to exactly 32 mm height, not a half-height confusion.
    bbox=mi.load_dict(obj['baffle_1']).bbox()
    assert np.isclose(float(bbox.max.z-bbox.min.z),.032,atol=1e-6)


def test_phase_figures_do_not_mix_phases_and_keep_scales(tmp_path, monkeypatch):
    from simulate import save_phase_figures, replot_results
    from matplotlib.figure import Figure
    original=Figure.savefig
    captured={}
    def inspect(fig, path, **kwargs):
        profiles=[ax for ax in fig.axes if ax.get_ylabel()=='Relative incident field (uncalibrated)']
        captured[Path(path).name]=[(ax.lines[0].get_ydata().copy(),ax.get_ylim()) for ax in profiles]
        return original(fig,path,**kwargs)
    monkeypatch.setattr(Figure,'savefig',inspect)
    records=[]
    for phase in [0,2]:
        for case in ['baffles','mask_baffles']:
            stem=f'{case}_phase{phase}'
            im=np.ones((4,4))*(phase+1)
            np.save(tmp_path/(stem+'.npy'),im)
            np.savetxt(tmp_path/(stem+'.csv'),np.c_[[.1,.2,.3],[phase+1]*3,[4]*3],
                       delimiter=',',header='u,field,count',comments='')
            records.append({'case':case,'phase':phase,'image_file':stem+'.npy','profile_file':stem+'.csv'})
    (tmp_path/'summary.json').write_text(json.dumps({'records':records}))
    (tmp_path/'config_used.json').write_text(json.dumps({'roi_mm':[8,8]}))
    before={p.name:p.read_bytes() for p in tmp_path.glob('*.npy')}
    assert replot_results(tmp_path)==0
    assert set(captured)=={'phase_0.png','phase_2.png'}
    assert all(np.all(y==1) for y,lim in captured['phase_0.png'])
    assert all(np.all(y==3) for y,lim in captured['phase_2.png'])
    limits=[lim for data in captured.values() for _,lim in data]
    assert all(lim==limits[0] for lim in limits)
    assert all((tmp_path/name).read_bytes()==data for name,data in before.items())
    assert all((tmp_path/name).stat().st_size>0 for name in captured)


def test_balanced_led_array_center_and_phase_counts():
    from simulate import led_layout
    d,cfg=load_config(CONFIG);bars=led_layout(d,cfg)
    assert len(bars)==16
    assert [sum(p==k for _,p,_ in bars) for k in range(4)]==[4]*4
    central={i:(p,x) for i,p,x in bars if i in range(4)}
    assert [central[i][0] for i in range(4)]==list(range(4))
    assert np.allclose([central[i][1] for i in range(4)],[-37.15676250697846,-12.385587502326153,12.385587502326153,37.15676250697846])
    assert np.isclose(sum(x for _,_,x in bars),0)
    legacy=json.loads((CONFIG.parent/'previous_120_central8mm.json').read_text())
    old=led_layout(legacy,cfg)
    assert len(old)==9 and [sum(p==k for _,p,_ in old) for k in range(4)]==[3,2,2,2]


def test_full_width_profile_is_not_period_folded_or_zero_padded():
    from simulate import horizontal_profile
    w,h=256,64;roi=[8.,8.];slope=1/3
    x=roi[0]/2-(np.arange(w)+.5)*roi[0]/w
    y=roi[1]/2-(np.arange(h)+.5)*roi[1]/h
    X,Y=np.meshgrid(x,y)
    im=2+np.cos(2*np.pi*(X+slope*Y-1.3)/.7)
    xx,p,count=horizontal_profile(im,roi,slope)
    assert len(xx)==w and xx[0]<-3.9 and xx[-1]>3.9
    assert np.max(abs(p-(2+np.cos(2*np.pi*(xx-1.3)/.7))))<.02
    _,constant,count=horizontal_profile(np.full((h,w),3.),roi,slope)
    assert np.allclose(constant,3.)
    assert count[0]<h and count[w//2]==h


def test_spatial_overlap_index_has_defined_limits_and_scale_invariance():
    from simulate import phase_overlap_fields
    fields=np.array([[[4.,1.,1.,0.]],[[0.,1.,1.,0.]],[[0.,0.,1.,0.]],[[0.,0.,1.,0.]]])
    total,fraction,index=phase_overlap_fields(fields)
    assert np.allclose(index[0,:3],[0.,.5,.75])
    assert np.isnan(index[0,3])
    assert np.allclose(fraction.sum(axis=0)[total>0],1.)
    _,f2,m2=phase_overlap_fields(fields*7)
    assert np.allclose(fraction,f2)
    assert np.allclose(index,m2,equal_nan=True)
    with pytest.raises(ValueError):phase_overlap_fields(fields[:3])
    with pytest.raises(ValueError):phase_overlap_fields(-fields)


def test_overlay_requires_complete_phases_and_preserves_source_data(tmp_path):
    from simulate import save_phase_overlays
    records=[]
    before={}
    for phase in range(4):
        name=f'case_phase{phase}.npy'
        image=np.zeros((8,8));image[:,phase*2:(phase+1)*2]=1
        np.save(tmp_path/name,image);before[name]=(tmp_path/name).read_bytes()
        records.append({'case':'test','phase':phase,'image_file':name})
    assert save_phase_overlays(tmp_path,records[:3],[8,8])==[]
    files=save_phase_overlays(tmp_path,records,[8,8])
    assert files==['phase_overlay.png','phase_overlay_zoom.png']
    raw=np.load(tmp_path/'test_phase_overlap.npz')
    assert np.allclose(raw['nondominant_fraction'],0.)
    assert all((tmp_path/n).read_bytes()==b for n,b in before.items())
    assert all((tmp_path/name).stat().st_size>0 for name in files)
