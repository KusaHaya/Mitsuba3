"""Configurable LED/lenticular illumination experiment. Run from VS Code or CLI.

This is geometric light transport, not a calibrated LCD crosstalk simulator.
All user distances are millimeters. Scene geometry is converted to meters.
"""
from __future__ import annotations
import argparse
from dataclasses import fields
from datetime import datetime
import json
import math
from pathlib import Path
import sys
import time

import numpy as np
from optics import OpticsConfig, lens_coordinates
from run import write_binary_ply

ROOT = Path(__file__).resolve().parent
CASES = ('baseline', 'mask', 'baffles', 'mask_baffles')


def load_config(path, mode='preview'):
    data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    allowed = {f.name for f in fields(OpticsConfig)}
    unknown = set(data['optics']) - allowed
    if unknown:
        raise ValueError(f'Unknown optics setting(s): {sorted(unknown)}')
    optics = dict(data['optics'])
    distance = data['led_to_vertex_mm']
    optics['led_to_flat_mm'] = distance - optics.get('thickness_mm', 2.)
    cfg = OpticsConfig(**optics)
    cfg.validate()
    if not all(math.isfinite(getattr(cfg, f.name)) for f in fields(OpticsConfig)):
        raise ValueError('All optics settings must be finite')
    positive = [distance, data['screen_from_vertex_mm'], *data['roi_mm'],
                data['baffles']['height_mm'], data['baffles']['thickness_mm']]
    if not all(math.isfinite(x) and x > 0 for x in positive):
        raise ValueError('Distances, ROI, and baffle dimensions must be finite and positive')
    if cfg.led_to_flat_mm <= 0:
        raise ValueError('LED-to-vertex distance must exceed lens thickness')
    if not math.isfinite(cfg.ior) or cfg.ior <= 1 or cfg.emitter_radiance <= 0:
        raise ValueError('Require ior > 1 and positive emitter radiance')
    if cfg.lens_count % 2:
        raise ValueError('Use an even lens_count to retain the same crest origin')
    if cfg.led_count_each_side < 3:
        raise ValueError('led_count_each_side >= 3 is needed to represent all four phases')
    if data['screen_medium'] not in ('air', 'pmma'):
        raise ValueError('screen_medium must be air or pmma')
    mask = data['mask']
    if not 0 < mask['open_fraction'] <= 1:
        raise ValueError('Mask open_fraction must be in (0, 1]')
    if not 0 < mask['z_mm'] < data['screen_from_vertex_mm']:
        raise ValueError('Require 0 < mask z_mm < screen_from_vertex_mm')
    normal_pitch = cfg.led_pitch_horizontal_mm / math.sqrt(1+cfg.normal_slope**2)
    if data['baffles']['thickness_mm'] >= normal_pitch:
        raise ValueError('Baffle thickness must be smaller than projected LED pitch')
    if data['baffles']['height_mm'] >= cfg.led_to_flat_mm:
        raise ValueError('Baffles must not intersect the lens entry face')
    if not data['cases'] or len(set(data['cases'])) != len(data['cases']):
        raise ValueError('cases must be nonempty and contain no duplicates')
    for name in data['cases']:
        if name not in CASES:
            raise ValueError(f'Unknown case: {name}')
    render = data['render'][mode]
    if any(not isinstance(render[k], int) or render[k] <= 0 for k in ('width','height','spp')):
        raise ValueError('Render width, height, spp must be positive integers')
    if abs(render['width']/render['height'] - data['roi_mm'][0]/data['roi_mm'][1]) > .001:
        raise ValueError('Render width/height must match ROI width/height')
    if not isinstance(data['render']['seed'], int) or data['render']['seed'] < 0:
        raise ValueError('Seed must be a nonnegative integer')
    if data['render']['threads'] < 1 or data['render']['max_depth'] < 4:
        raise ValueError('Require threads >= 1 and max_depth >= 4')
    # Ensure the receiver lies inside the cropped lens footprint.
    angle = math.atan(cfg.normal_slope)
    u_span = abs(math.cos(angle))*data['roi_mm'][0]+abs(math.sin(angle))*data['roi_mm'][1]
    v_span = abs(math.sin(angle))*data['roi_mm'][0]+abs(math.cos(angle))*data['roi_mm'][1]
    if u_span >= cfg.lens_count*cfg.pitch_mm or v_span >= cfg.v_length_mm:
        raise ValueError('Lens crop must be larger than the receiving ROI')
    return data, cfg


def scene_dict(mi, data, cfg, mesh, phase, case, mode):
    T = mi.ScalarTransform4f
    mm = .001
    width, height = data['roi_mm']
    screen = data['screen_from_vertex_mm']
    sample = data['render'][mode]
    angle = math.atan(cfg.normal_slope)
    nx, ny = math.cos(angle), math.sin(angle)
    camera_distance = min(1., screen*.5)
    scene = {
        'type':'scene',
        'integrator':{'type':'ptracer', 'max_depth':data['render']['max_depth'],
                      'samples_per_pass':min(256,sample['spp']), 'hide_emitters':True},
        'lens':{'type':'ply','filename':str(mesh.resolve()),'face_normals':True,
                'bsdf':{'type':'dielectric','int_ior':cfg.ior,'ext_ior':1.}},
        'receiver':{'type':'rectangle',
            'to_world':T.translate([0,0,screen*mm]) @ T.rotate([1,0,0],180)
                @ T.scale([width*mm/2,height*mm/2,1]),
            'bsdf':{'type':'diffuse','reflectance':{'type':'rgb','value':[1.,1.,1.]}}},
        # ptracer cannot connect to an orthographic sensor in the tested backend.
        # Perspective camera remains between the lens and receiver, so it sees the lit side.
        'sensor':{'type':'perspective','fov_axis':'x',
            'fov':math.degrees(2*math.atan(width/(2*camera_distance))),
            'to_world':T.look_at(origin=[0,0,(screen-camera_distance)*mm],
                                target=[0,0,screen*mm],up=[0,1,0]),
            'near_clip':1e-6, 'far_clip':max(1.,screen*mm*10),
            'film':{'type':'hdrfilm','width':sample['width'],'height':sample['height'],
                    'pixel_format':'rgb','component_format':'float32','rfilter':{'type':'box'}},
            'sampler':{'type':'independent','sample_count':sample['spp']}}
    }
    for i in range(-cfg.led_count_each_side,cfg.led_count_each_side+1):
        if i % 4 != phase:
            continue
        u = i*cfg.led_pitch_horizontal_mm*nx
        scene[f'led_{i+cfg.led_count_each_side}']={
            'type':'rectangle',
            'to_world':T.translate([nx*u*mm,ny*u*mm,-data['led_to_vertex_mm']*mm])
                @ T.rotate([0,0,1],math.degrees(angle))
                @ T.scale([cfg.led_width_horizontal_mm*nx*mm/2,cfg.v_length_mm*mm/2,1]),
            'emitter':{'type':'area','radiance':cfg.emitter_radiance}}
    if data['screen_medium']=='pmma':
        # Ideal incident-irradiance plane inside PMMA, NOT a physical diffuser/LCD stack.
        # Both receiver and virtual camera are embedded. Do not infer absolute luminance.
        depth = screen + 1.
        size = max(width,height,cfg.v_length_mm,cfg.lens_count*cfg.pitch_mm)*2
        scene['pmma_after_lens']={
            'type':'cube',
            'to_world':T.translate([0,0,depth*mm/2]) @ T.scale([size*mm,size*mm,depth*mm/2]),
            'bsdf':{'type':'dielectric','int_ior':cfg.ior,'ext_ior':1.}}
    if case in ('mask','mask_baffles'):
        for j in range(-cfg.lens_count//2,cfg.lens_count//2):
            u=(j+.5)*cfg.pitch_mm
            scene[f'mask_{j+cfg.lens_count}']={
                'type':'rectangle',
                'to_world':T.translate([nx*u*mm,ny*u*mm,data['mask']['z_mm']*mm])
                    @ T.rotate([0,0,1],math.degrees(angle))
                    @ T.scale([cfg.pitch_mm*(1-data['mask']['open_fraction'])*mm/2,
                               cfg.v_length_mm*mm/2,1]),
                'bsdf':{'type':'diffuse','reflectance':0.}}
    if case in ('baffles','mask_baffles'):
        h=data['baffles']['height_mm']; thick=data['baffles']['thickness_mm']
        for j in range(-cfg.led_count_each_side-1,cfg.led_count_each_side+1):
            u=(j+.5)*cfg.led_pitch_horizontal_mm*nx
            scene[f'baffle_{j+cfg.led_count_each_side+1}']={
                'type':'cube',
                'to_world':T.translate([nx*u*mm,ny*u*mm,(-data['led_to_vertex_mm']+h/2)*mm])
                    @ T.rotate([0,0,1],math.degrees(angle))
                    @ T.scale([thick*mm/2,cfg.v_length_mm*mm/2,h*mm/2]),
                'bsdf':{'type':'diffuse','reflectance':0.}}
    return scene


def folded_profile(image, roi_mm, slope, period_mm, bins=128):
    """Average along grooves. Camera +z/up+y maps both pixel axes to decreasing world coords."""
    h,w=image.shape
    x=roi_mm[0]/2-(np.arange(w)+.5)*roi_mm[0]/w
    y=roi_mm[1]/2-(np.arange(h)+.5)*roi_mm[1]/h
    X,Y=np.meshgrid(x,y)
    u=(X+slope*Y)/math.sqrt(1+slope*slope)
    index=np.floor((u.ravel()%period_mm)/period_mm*bins).astype(int)
    count=np.bincount(index,minlength=bins)
    total=np.bincount(index,weights=image.ravel(),minlength=bins)
    profile=np.full(bins,np.nan)
    np.divide(total,count,out=profile,where=count>0)
    return (np.arange(bins)+.5)*period_mm/bins,profile,count


def save_overview(output, records, roi):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    cases=list(dict.fromkeys(r['case'] for r in records))
    fig,axes=plt.subplots(2,len(cases),figsize=(6*len(cases),8),squeeze=False,layout='constrained')
    global_top=0
    for col,case in enumerate(cases):
        subset=[r for r in records if r['case']==case]
        for rec in subset:
            p=np.loadtxt(output/rec['profile_file'],delimiter=',',skiprows=1)
            axes[0,col].plot(p[:,0],p[:,1],label=f"Phase {rec['phase']}")
            global_top=max(global_top,float(np.nanmax(p[:,1])))
        axes[0,col].set(title=case,xlabel='Coordinate normal to grooves (mm)',
                        ylabel='Relative incident field (uncalibrated)')
        axes[0,col].legend()
        rec=subset[0];im=np.load(output/rec['image_file'])
        # Reverse both array axes for increasing world x and y with origin lower.
        axes[1,col].imshow(im[::-1,::-1],origin='lower',aspect='equal',
            extent=[-roi[0]/2,roi[0]/2,-roi[1]/2,roi[1]/2],vmin=0,vmax=float(np.quantile(im,.995)))
        axes[1,col].set(title=f"{case}: phase {rec['phase']}",xlabel='World x (mm)',ylabel='World y (mm)')
    for ax in axes[0]:ax.set_ylim(0,max(global_top*1.1,1e-10))
    fig.suptitle('Exploratory simulation — not calibrated crosstalk / no convergence claim')
    fig.savefig(output/'overview.png',dpi=150)
    plt.close(fig)


def save_phase_figures(output, records, roi):
    """One file per phase, with matching profile/image and common scales across phases."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    if not records:
        raise ValueError('No rendered records to plot')
    cases=list(dict.fromkeys(r['case'] for r in records))
    phases=sorted({r['phase'] for r in records})
    profiles={}; images={}
    for rec in records:
        key=(rec['case'],rec['phase'])
        if key in profiles:
            raise ValueError(f'Duplicate result: {key}')
        profiles[key]=np.loadtxt(output/rec['profile_file'],delimiter=',',skiprows=1)
        images[key]=np.load(output/rec['image_file'])
    ymax=max(float(np.nanmax(p[:,1])) for p in profiles.values())
    image_max=max(float(np.quantile(im,.995)) for im in images.values())
    ymax=max(ymax*1.1,1e-10); image_max=max(image_max,1e-10)
    colors=['tab:blue','tab:orange','tab:green','tab:red']
    files=[]
    for phase in phases:
        fig,axes=plt.subplots(2,len(cases),figsize=(6*len(cases),8),squeeze=False,layout='constrained')
        for col,case in enumerate(cases):
            key=(case,phase)
            if key not in profiles:
                axes[0,col].set(title=f'{case}: phase {phase} not rendered')
                axes[1,col].axis('off')
                continue
            p=profiles[key]; im=images[key]
            axes[0,col].plot(p[:,0],p[:,1],color=colors[phase],label=f'Phase {phase}')
            axes[0,col].set(title=f'{case}: phase {phase} only',
                xlabel='Folded coordinate normal to grooves (mm)',
                ylabel='Relative incident field (uncalibrated)',ylim=(0,ymax))
            axes[0,col].legend()
            view=axes[1,col].imshow(im[::-1,::-1],origin='lower',aspect='equal',
                extent=[-roi[0]/2,roi[0]/2,-roi[1]/2,roi[1]/2],vmin=0,vmax=image_max)
            axes[1,col].set(title=f'{case}: phase {phase} illumination',
                xlabel='World x (mm)',ylabel='World y (mm)')
            fig.colorbar(view,ax=axes[1,col],label='Relative incident field')
        fig.suptitle(f'Phase {phase} — common scales for all phases/cases; exploratory, uncalibrated')
        name=f'phase_{phase}.png';fig.savefig(output/name,dpi=150);plt.close(fig);files.append(name)
    return files


def replot_results(output):
    output=Path(output)
    if str(output)=='latest':
        candidates=[p.parent for p in (ROOT/'results').glob('*/summary.json')
                    if (p.parent/'config_used.json').is_file()]
        if not candidates:
            raise ValueError('No saved results found under results/')
        output=max(candidates,key=lambda p:(p/'summary.json').stat().st_mtime_ns)
    summary=json.loads((output/'summary.json').read_text(encoding='utf-8'))
    config=json.loads((output/'config_used.json').read_text(encoding='utf-8'))
    files=save_phase_figures(output,summary['records'],config['roi_mm'])
    print(f'Created {", ".join(files)} in {output.resolve()}\nReused saved data; no ray tracing was run.')
    return 0


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=ROOT/'configs/current.json')
    parser.add_argument('--mode',choices=['preview','quality'],default='preview')
    parser.add_argument('--variant', choices=['llvm_ad_rgb', 'cuda_ad_rgb', 'scalar_rgb'],
                        help='Override the renderer backend; scalar_rgb avoids LLVM JIT')
    parser.add_argument('--spp', type=int, help='Override samples per pixel for this run')
    parser.add_argument('--case',choices=CASES,action='append',dest='cases')
    parser.add_argument('--phase',type=int,choices=range(4),action='append',dest='phases')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--validate-only',action='store_true')
    parser.add_argument('--plot-only', type=Path, metavar='RESULT_FOLDER_OR_latest',
                        help='Create phase-specific figures from saved data, without rendering')
    args=parser.parse_args(argv)
    if args.plot_only is not None:
        try:
            return replot_results(args.plot_only)
        except (ValueError, KeyError, OSError) as exc:
            parser.error(f'Cannot plot saved results: {exc}')
    try:data,cfg=load_config(args.config,args.mode)
    except (ValueError,KeyError,TypeError,OSError) as exc:
        parser.error(f'Invalid configuration: {exc}')
    if args.variant:
        data['render']['variant'] = args.variant
    if args.spp is not None:
        if args.spp <= 0:
            parser.error('--spp must be positive')
        data['render'][args.mode]['spp'] = args.spp
    sample=data['render'][args.mode]
    # This is an approximate folding period, not a measured result.
    q=data['screen_from_vertex_mm']/(cfg.ior if data['screen_medium']=='pmma' else 1.)
    a=cfg.led_to_flat_mm+cfg.thickness_mm/cfg.ior
    period=cfg.pitch_mm*(1+q/a)
    print(f'Config: {args.config.resolve()}',flush=True)
    print(f'Renderer: {data["render"]["variant"]}', flush=True)
    print(f'LED to vertex {data["led_to_vertex_mm"]} mm; screen {data["screen_from_vertex_mm"]} mm ({data["screen_medium"]})',flush=True)
    print(f'Approximate AIR effective focal length R/(n-1): {cfg.radius_mm/(cfg.ior-1):.6f} mm',flush=True)
    print(f'Approximate folding period: {period:.6f} mm normal to grooves (not a measurement)',flush=True)
    if args.validate_only:
        print('Configuration valid. No renderer imported and no simulation run.')
        return 0
    try:
        import mitsuba as mi
        import drjit as dr
        mi.set_variant(data['render']['variant'])
        dr.set_thread_count(data['render']['threads'])
    except (ImportError,RuntimeError,AttributeError) as exc:
        print(f'Cannot initialize Mitsuba: {exc}\nUse the project .venv and install requirements.txt.\n'
              'For llvm_ad_rgb on Windows, install LLVM and see README.md (DRJIT_LIBLLVM_PATH).',file=sys.stderr)
        return 2
    output=args.output or ROOT/'results'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    if output.exists() and any(output.iterdir()):
        parser.error('Output directory is not empty. Choose a NEW --output directory to avoid stale results.')
    output.mkdir(parents=True,exist_ok=True)
    (output/'config_used.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    mesh=output/'lens.ply';vertices,faces=lens_coordinates(cfg);write_binary_ply(mesh,vertices,faces)
    cases=args.cases or data['cases'];phases=args.phases or list(range(4));records=[]
    warnings=[
        'EXPLORATORY: calibration and mesh/pixel/sample convergence not established.',
        'PMMA mode embeds an ideal receiver in PMMA; not a measured diffuser or complete LCD stack.',
        'No measured LED distribution, spectral dispersion, diffraction, LCD switching, or observer model.',
        'No absolute luminance or real-system crosstalk percentage is computed.',
        'Profiles use an APPROXIMATE geometric folding period, not a measured period.',
        'The prior free-space benchmark had ~11% normalization discrepancy; calibration remains unresolved.'
    ]
    for case in cases:
        for phase in phases:
            started=time.monotonic();print(f'Rendering {case}, phase {phase}, {sample} ...',flush=True)
            try:
                scene=mi.load_dict(scene_dict(mi,data,cfg,mesh,phase,case,args.mode))
                image=np.asarray(mi.render(scene,spp=sample['spp'],seed=data['render']['seed'])).mean(axis=2)*math.pi
            except RuntimeError as exc:
                print(f'Render failed: {exc}',file=sys.stderr);return 3
            if not np.isfinite(image).all() or np.max(image)<=0:
                print('Render contains no finite positive light; do not interpret as a valid barrier.',file=sys.stderr);return 4
            stem=f'{case}_phase{phase}';np.save(output/(stem+'.npy'),image)
            x,p,count=folded_profile(image,data['roi_mm'],cfg.normal_slope,period)
            np.savetxt(output/(stem+'.csv'),np.c_[x,p,count],delimiter=',',
                       header='normal_coordinate_mm,relative_incident_field,pixel_count',comments='')
            records.append({'case':case,'phase':phase,'mean_relative_field':float(image.mean()),
                'image_file':stem+'.npy','profile_file':stem+'.csv','seconds':time.monotonic()-started})
            result={'mitsuba_version':mi.__version__,'variant':data['render']['variant'],
                    'mode':args.mode,'render_settings':sample,'warnings':warnings,
                    'approximate_folding_period_normal_mm':period,'records':records,
                    'fwhm_mm':None,'crosstalk_percent':None,'reason':'Not validated: use raw outputs and convergence tests.'}
            (output/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
            print(f'Saved {stem}; mean={image.mean():.6g}, {time.monotonic()-started:.1f}s',flush=True)
    save_overview(output,records,data['roi_mm'])
    phase_files=save_phase_figures(output,records,data['roi_mm'])
    print(f'Complete: {output.resolve()}\nOpen {", ".join(phase_files)} for separate phases, or overview.png for the overlay. See summary.json warnings.')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
