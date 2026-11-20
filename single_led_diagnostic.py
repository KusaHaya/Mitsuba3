r"""Single-LED optical diagnostic. Keeps all baffles and the full lens unchanged.
Windows: .\.venv\Scripts\python.exe single_led_diagnostic.py --plan-only
Windows GPU: .\.venv\Scripts\python.exe single_led_diagnostic.py
"""
from __future__ import annotations
import argparse,csv,json,math,time,zipfile
from datetime import datetime
from pathlib import Path
import numpy as np
from simulate import ROOT,load_config,led_layout,scene_dict,lens_mesh_config,folded_profile,horizontal_profile
from scan_tiles import peak_stats,tile_data,valid_field
from optics import lens_coordinates
from run import write_binary_ply


def select_leds(data,cfg,indices=None):
    """Indices are zero-based physical positions from the left, never phase IDs."""
    layout=led_layout(data,cfg)
    if indices is None:
        indices=[min(range(len(layout)),key=lambda j:abs(layout[j][2]))]
    if len(indices)!=len(set(indices)) or any(i<0 or i>=len(layout) for i in indices):
        raise ValueError(f'LED indices must be distinct integers in 0..{len(layout)-1}')
    return [dict(index=j,phase=layout[j][1],x_mm=layout[j][2]) for j in indices]


def isolate_source(scene,index):
    """Remove only unselected emitting bars; never rebuild or reposition geometry."""
    key=f'led_{index}'
    if key not in scene:raise ValueError(f'{key} is not active in this phase')
    return {k:v for k,v in scene.items() if not k.startswith('led_') or k==key}


def shorten_source(scene,index,length,original_length,transform):
    """Change only the selected emitter's local long axis, retaining every baffle."""
    if length is None:return scene
    if not math.isfinite(length) or length<=0 or length>original_length:
        raise ValueError('LED length must be positive and no longer than the original bar')
    key=f'led_{index}'
    result=dict(scene);result[key]=dict(scene[key])
    result[key]['to_world']=scene[key]['to_world'] @ transform.scale([1.,length/original_length,1.])
    return result


def analyze(folder):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    folder=Path(folder);m=json.loads((folder/'diagnostic_config.json').read_text())
    d=m['physical_config'];n=d['optics']['ior'];slope=d['optics']['normal_slope'];nx=1/math.sqrt(1+slope*slope)
    a=d['led_to_vertex_mm']-(d['optics']['thickness_mm']+d.get('rear_acrylic_mm',0))*(1-1/n)
    q=d['screen_from_vertex_mm']/(n if d['screen_medium']=='pmma' else 1)
    period=d['optics']['pitch_mm']*(1+q/a)
    rows=[];profiles=[]
    fig,axes=plt.subplots(len(m['leds']),2,figsize=(12,3*len(m['leds'])),squeeze=False)
    for i,led in enumerate(m['leds']):
        for col,case in enumerate(['baffles','mask_baffles']):
            ax=axes[i,col]
            for spp in m['spp']:
                for seed in m['seeds']:
                    name=f'{case}_led{led["index"]:02d}_spp{spp}_seed{seed}'
                    field=np.load(folder/(name+'.npy'))
                    u,p,count=folded_profile(field,m['tile']['size_mm'],slope,period,128)
                    stat=peak_stats(p,period,nx)
                    rows.append(dict(led=led['index'],phase=led['phase'],case=case,spp=spp,seed=seed,
                                     view_x_mm=m['tile']['center_mm'][0],led_x_mm=led['x_mm'],
                                     mean=float(field.mean()),nonzero_fraction=float(np.count_nonzero(field)/field.size),
                                     emitting_length_mm=m.get('emitting_length_mm',d.get('led_array',{}).get('bar_length_mm',d['optics']['v_length_mm'])),
                                     **stat,warning='local folded estimate; not crosstalk or converged PSF'))
                    x,h,c=horizontal_profile(field,m['tile']['size_mm'],slope)
                    ax.plot(x+m['tile']['center_mm'][0],h,label=f'{spp} spp, seed {seed}',alpha=.75,lw=.8)
                    profiles.extend(dict(run=name,x_mm=float(xx+m['tile']['center_mm'][0]),field=float(vv)) for xx,vv in zip(x,h))
            ax.set_title(f'{case}: LED {led["index"]}, phase {led["phase"]}');ax.set_xlabel('Screen stripe-aligned x (mm)');ax.grid(alpha=.2);ax.legend(fontsize=7)
    fig.suptitle(f"One LED; emitting length {m.get('emitting_length_mm', d.get('led_array',{}).get('bar_length_mm','original'))} mm; all baffles retained")
    fig.tight_layout();fig.savefig(folder/'profiles.png',dpi=140);plt.close(fig)
    for name,rr in [('metrics.csv',rows),('profiles.csv',profiles)]:
        with (folder/name).open('w',newline='',encoding='utf-8-sig') as f:
            w=csv.DictWriter(f,fieldnames=list(rr[0]));w.writeheader();w.writerows(rr)
    with zipfile.ZipFile(folder/'single_led_results.zip','w',zipfile.ZIP_DEFLATED) as z:
        for p in folder.iterdir():
            if p.suffix in ('.npy','.json','.csv','.png'):z.write(p,p.name)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',type=Path,default=ROOT/'configs/current.json')
    p.add_argument('--variant',choices=['cuda_ad_rgb','llvm_ad_rgb','scalar_rgb'],default='cuda_ad_rgb')
    p.add_argument('--led',type=int,action='append',help='Zero-based physical LED index, repeatable')
    p.add_argument('--view-x',type=float,default=0.)
    p.add_argument('--led-length-mm',type=float,help='Emitting segment length only; all baffles stay unchanged')
    p.add_argument('--spp',type=int,action='append',help='Repeat to compare sample counts; default 256')
    p.add_argument('--seed',type=int,action='append',help='Independent repeats; default 17')
    p.add_argument('--pixels',type=int,default=512)
    p.add_argument('--samples-per-pass',type=int,default=4)
    p.add_argument('--output',type=Path)
    p.add_argument('--resume',type=Path)
    p.add_argument('--plan-only',action='store_true')
    p.add_argument('--analyze-only',type=Path)
    args=p.parse_args(argv)
    if args.analyze_only:analyze(args.analyze_only);return 0
    try:
        d,cfg=load_config(args.config);leds=select_leds(d,cfg,args.led)
        spp=sorted(set(args.spp or [256]));seeds=sorted(set(args.seed or [17]))
        original_length=d.get('led_array',{}).get('bar_length_mm',cfg.v_length_mm)
        if args.led_length_mm is not None and (not math.isfinite(args.led_length_mm) or not 0<args.led_length_mm<=original_length):
            raise ValueError('LED length must be positive and no longer than the original bar')
        if min(spp)<1 or min(seeds)<0 or max(seeds)>=2**32 or args.samples_per_pass<1:raise ValueError('Invalid sampling settings')
        if args.pixels<16 or args.pixels%8:raise ValueError('pixels must be >=16 and divisible by 8')
        if not math.isfinite(args.view_x) or abs(args.view_x)+1>d['roi_mm'][0]/2:raise ValueError('View outside screen')
    except (ValueError,OSError,KeyError) as exc:p.error(str(exc))
    tile=dict(center_mm=[args.view_x,0.],size_mm=[2.,.25],pixels=[args.pixels,args.pixels//8])
    d['render']['variant']=args.variant
    manifest=dict(physical_config=d,leds=leds,tile=tile,spp=spp,seeds=seeds,
                  samples_per_pass=args.samples_per_pass,integrator='path',
                  emitting_length_mm=args.led_length_mm if args.led_length_mm is not None else original_length,
                  assumption='Diagnose one source; no assumption that different sources overlap')
    print(json.dumps(dict(leds=leds,view_x=args.view_x,spp=spp,seeds=seeds,
                         jobs=2*len(leds)*len(spp)*len(seeds),variant=args.variant,
                         emitting_length_mm=manifest['emitting_length_mm']),indent=2))
    if args.plan_only:return 0
    folder=args.resume or args.output or ROOT/'results'/('single_led_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    if args.resume:
        if json.loads((folder/'diagnostic_config.json').read_text())!=manifest:p.error('Resume settings differ')
    elif folder.exists() and any(folder.iterdir()):p.error('Output folder is not empty')
    import mitsuba as mi
    import drjit as dr
    mi.set_variant(args.variant);dr.set_thread_count(d['render']['threads'])
    folder.mkdir(parents=True,exist_ok=True)
    (folder/'diagnostic_config.json').write_text(json.dumps(manifest,indent=2)+'\n')
    mesh=folder/'lens.ply'
    if not mesh.exists():
        v,f=lens_coordinates(lens_mesh_config(d,cfg),d.get('lens_outline_mm'));write_binary_ply(mesh,v,f)
    local=tile_data(d,tile);local['render']['preview']['spp']=args.samples_per_pass
    total=2*len(leds)*len(spp)*len(seeds);done=0
    for led in leds:
        for case in ['baffles','mask_baffles']:
            obj=isolate_source(scene_dict(mi,local,cfg,mesh,led['phase'],case,'preview'),led['index'])
            obj=shorten_source(obj,led['index'],args.led_length_mm,original_length,mi.ScalarTransform4f)
            obj['integrator']={'type':'path','max_depth':d['render']['max_depth'],'hide_emitters':True}
            assert len([k for k in obj if k.startswith('led_')])==1
            scene=mi.load_dict(obj)
            for count in spp:
                for seed in seeds:
                    path=folder/f'{case}_led{led["index"]:02d}_spp{count}_seed{seed}.npy'
                    if valid_field(path,(args.pixels//8,args.pixels)):
                        done+=1;print(f'[{done}/{total}] Already saved: {path.name}',flush=True);continue
                    started=time.monotonic();acc=np.zeros((args.pixels//8,args.pixels),np.float64)
                    remaining=count;part=0
                    while remaining:
                        batch=min(remaining,args.samples_per_pass)
                        im=np.asarray(mi.render(scene,spp=batch,seed=(seed+part*1000003)%(2**32)))
                        acc+=im.mean(2)*math.pi*batch;remaining-=batch;part+=1
                    field=(acc/count).astype(np.float32)
                    if not np.isfinite(field).all() or (field<0).any():raise ValueError('Invalid rendered field')
                    temporary=path.with_suffix('.tmp')
                    with temporary.open('wb') as handle:np.save(handle,field)
                    temporary.replace(path)
                    done+=1;print(f'[{done}/{total}] LED {led["index"]} {case}, {count} spp, seed {seed}: {time.monotonic()-started:.1f}s',flush=True)
            del scene
            if args.variant.startswith('cuda'):dr.sync_thread();dr.flush_malloc_cache()
    analyze(folder);print(f'Send: {folder.resolve()/"single_led_results.zip"}');return 0

if __name__=='__main__':raise SystemExit(main())
