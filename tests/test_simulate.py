import copy
import json
from pathlib import Path
import math
import numpy as np
import pytest
from simulate import load_config, folded_profile, scene_dict

CONFIG = Path(__file__).resolve().parents[1]/'configs/current.json'


def write_config(tmp_path, modify):
    data=json.loads(CONFIG.read_text(encoding='utf-8'))
    modify(data)
    p=tmp_path/'config.json';p.write_text(json.dumps(data))
    return p


def test_vertex_distance_and_screen_are_unambiguous():
    d,cfg=load_config(CONFIG)
    assert cfg.led_to_flat_mm==118
    assert cfg.led_to_flat_mm+cfg.thickness_mm==d['led_to_vertex_mm']==120
    assert d['screen_from_vertex_mm']==1.5


@pytest.mark.parametrize('modify',[
    lambda d:d.update(led_to_vertex_mm=1),
    lambda d:d['mask'].update(open_fraction=1.1),
    lambda d:d['baffles'].update(height_mm=120),
    lambda d:d['render']['preview'].update(height=128),
    lambda d:d['optics'].update(lens_count=3),
    lambda d:d['optics'].update(led_count_each_side=1),
    lambda d:d.update(cases=[]),
    lambda d:d['optics'].update(normal_slope=float('nan')),
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


def test_mitsuba_scene_and_actual_render(tmp_path):
    mi=pytest.importorskip('mitsuba')
    mi.set_variant('llvm_ad_rgb')
    from optics import lens_coordinates
    from run import write_binary_ply
    d,cfg=load_config(CONFIG);d=copy.deepcopy(d)
    d['render']['preview']={'width':32,'height':32,'spp':64}
    mesh=tmp_path/'lens.ply';v,f=lens_coordinates(cfg);write_binary_ply(mesh,v,f)
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
