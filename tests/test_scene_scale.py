from dataclasses import replace
from pathlib import Path
import numpy as np
import pytest
from simulate import load_config,scene_dict,lens_mesh_config
from optics import lens_coordinates
from run import write_binary_ply


def test_real_ray_does_not_skip_lens_curve_after_acrylic(tmp_path):
    mi=pytest.importorskip('mitsuba');mi.set_variant('scalar_rgb')
    d,c=load_config(Path(__file__).resolve().parents[1]/'configs/current.json')
    d['roi_mm']=[4,4];d.pop('lens_outline_mm',None)
    c=replace(c,lens_count=8,v_length_mm=10)
    mesh=tmp_path/'lens.ply';v,f=lens_coordinates(lens_mesh_config(d,c));write_binary_ply(mesh,v,f)
    paths={}
    for scale in [1.,1000.]:
        d['render']['scene_scale']=scale
        scene=mi.load_dict(scene_dict(mi,d,c,mesh,1,'mask_baffles','preview'))
        nx,ny=3/np.sqrt(10),1/np.sqrt(10)
        ray=mi.Ray3f(mi.Point3f(nx*.12*.001*scale,ny*.12*.001*scale,.5*.001*scale),mi.Vector3f(0,0,-1))
        hits=[]
        for _ in range(3):
            si=scene.ray_intersect(ray);assert si.is_valid()
            hits.append((si.shape.id(),float(si.p.z)*1000/scale,float(si.n.z)))
            bs,weight=si.bsdf().sample(mi.BSDFContext(),si,.999,mi.Point2f(.5,.5))
            ray=si.spawn_ray(si.to_world(bs.wo))
        paths[scale]=hits
    assert paths[1.][0][0]=='pmma_after_lens'
    # Old metre-scale scene skips the curved entrance and reaches the rear flat surface.
    assert paths[1.][1][0]=='lens' and paths[1.][1][1]<-11.9
    # Corrected scale resolves the curve between z=-0.02 and 0 mm before rear surface.
    assert paths[1000.][0][0]=='pmma_after_lens'
    assert paths[1000.][1][0]=='lens' and -.02<paths[1000.][1][1]<0
    assert paths[1000.][1][2]>0 and paths[1000.][2][1]<-11.9
