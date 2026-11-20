from pathlib import Path
import io,json,contextlib
import numpy as np
import pytest
from simulate import load_config,scene_dict,lens_mesh_config
from scan_tiles import make_spot_tiles
from optics import lens_coordinates
from run import write_binary_ply
from rebuild_model import main

CONFIG=Path(__file__).resolve().parents[1]/'configs/rebuilt_v2.json'

def test_rebuilt_plans_keep_full_model_and_small_sampling():
    d,c=load_config(CONFIG)
    assert d['roi_mm']==[546,312] and d['led_array']['count']==19
    assert d['screen_from_vertex_mm']==1.5 and d['observer_evaluation']['acrylic_after_screen_mm']==5
    assert d['render']['scene_scale']==1000 and d['render']['origin_mode']=='view_center'
    t=make_spot_tiles(d,[0,-250,250],2,512)
    assert len(t)==3 and all(v['size_mm']==[2,.25] for v in t)
    for x in [[274],[0,0],[float('nan')]]:
        with pytest.raises(ValueError):make_spot_tiles(d,x)
    for args,jobs in [(['--plan-only'],8),(['--all-positions','--plan-only'],24)]:
        with contextlib.redirect_stdout(io.StringIO()) as output:assert main(args)==0
        assert f'"jobs": {jobs}' in output.getvalue()


def test_edge_local_origin_resolves_curved_interface(tmp_path):
    mi=pytest.importorskip('mitsuba');mi.set_variant('scalar_rgb')
    d,c=load_config(CONFIG)
    # A groove crest near the right side. Translate all optics, not just the camera.
    nx,ny=3/np.sqrt(10),1/np.sqrt(10);u=358*.7
    center=[nx*u,ny*u];d['view']['center_mm']=center
    mesh=tmp_path/'lens.ply';v,f=lens_coordinates(lens_mesh_config(d,c),d.get('lens_outline_mm'));write_binary_ply(mesh,v,f)
    paths={}
    for mode in ['global','view_center']:
        d['render']['origin_mode']=mode
        obj=scene_dict(mi,d,c,mesh,1,'mask_baffles','preview');scene=mi.load_dict(obj)
        offset=np.zeros(2) if mode=='view_center' else np.array(center)
        ray=mi.Ray3f(mi.Point3f(offset[0]+nx*.12,offset[1]+ny*.12,.5),mi.Vector3f(0,0,-1))
        hits=[]
        for _ in range(2):
            si=scene.ray_intersect(ray);assert si.is_valid();hits.append((si.shape.id(),float(si.p.z)))
            bs,_=si.bsdf().sample(mi.BSDFContext(),si,.999,mi.Point2f(.5,.5));ray=si.spawn_ray(si.to_world(bs.wo))
        paths[mode]=hits
    assert paths['global'][0][0]=='pmma_after_lens'
    assert paths['global'][1][0]=='lens' and paths['global'][1][1]<-11.9
    assert paths['view_center'][1][0]=='lens' and -.02<paths['view_center'][1][1]<0
