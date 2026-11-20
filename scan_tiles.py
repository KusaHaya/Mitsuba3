"""High-resolution, resumable local scans of the unchanged full optical model.

Tile images are estimates of illumination, not LCD/observer crosstalk.
Uses backward path tracing for small sensor windows; simulate.py retains ptracer.
"""
from __future__ import annotations
import argparse
import copy
import csv
from datetime import datetime
import itertools
import json
import math
from pathlib import Path
import time
import zipfile

import numpy as np
from simulate import (ROOT,load_config,led_layout,scene_dict,lens_mesh_config,
                      horizontal_profile,folded_profile)
from optics import lens_coordinates
from run import write_binary_ply


def make_tiles(data, regions, tile_mm=8., pixels=2048, y=0., limit=None, band_mm=200.):
    """Three identical bands covering the approximate four-LED illumination envelope."""
    span=band_mm
    if not math.isfinite(tile_mm) or not math.isfinite(band_mm) or band_mm<=0 or tile_mm<=0 or pixels<16 or pixels%8:
        raise ValueError('tile-mm must be positive; pixels must be >=16 and divisible by 8')
    if span>data['roi_mm'][0]:
        raise ValueError('Receiver is narrower than the requested band')
    count=math.ceil(span/tile_mm);width=span/count;height=width/8
    if not math.isfinite(y) or abs(y)+height/2>data['roi_mm'][1]/2:
        raise ValueError('Requested y lies outside receiver')
    edges=dict(center=0.,left=-(data['roi_mm'][0]-span)/2,
               right=(data['roi_mm'][0]-span)/2)
    tiles=[]
    for region in regions:
        middle=edges[region]
        band=[]
        for i in range(count):
            x=middle-span/2+(i+.5)*width
            band.append(dict(id=f'{region}_{i:03d}',region=region,index=i,
                             center_mm=[x,y],size_mm=[width,height],
                             pixels=[pixels,pixels//8]))
        # Get useful middle-of-band data first without changing the physical grid.
        tiles.extend(sorted(band,key=lambda t:abs(t['center_mm'][0]-middle)))
    return tiles[:limit] if limit else tiles


def tile_data(base,tile):
    data=copy.deepcopy(base)
    data['view']={k:tile[k] for k in ('center_mm','size_mm')}
    data['render']['preview'].update(width=tile['pixels'][0],height=tile['pixels'][1])
    return data


def field_path(folder,tile,case,phase):
    return folder/tile['id']/f'{case}_phase{phase}.npy'


def valid_field(path,shape):
    if not path.is_file():return False
    try:
        a=np.load(path,mmap_mode='r')
        return a.shape==shape and np.isfinite(a).all() and (a>=0).all()
    except (OSError,ValueError):return False


def peak_stats(p,period,nx):
    if not np.isfinite(p).all() or p.max()<=0:
        return dict(peak_normal_mm=None,width_horizontal_mm=None,contrast=None)
    # A small fixed smoothing kernel: report an estimate, not optical PSF FWHM.
    from scipy.ndimage import gaussian_filter1d
    z=gaussian_filter1d(p,.004/period*len(p),mode='wrap')
    k=int(np.argmax(z));base=float(np.quantile(z,.1));peak=float(z[k])
    contrast=(peak-base)/(peak+base) if peak+base else 0.
    if contrast<.05:
        return dict(peak_normal_mm=None,width_horizontal_mm=None,contrast=contrast)
    threshold=(peak+base)/2;left=right=0
    while left<len(z)//2 and z[(k-left-1)%len(z)]>=threshold:left+=1
    while right<len(z)//2 and z[(k+right+1)%len(z)]>=threshold:right+=1
    return dict(peak_normal_mm=(k+.5)*period/len(z),
                width_horizontal_mm=(left+right+1)*period/len(z)/nx,
                contrast=contrast)


def shape_overlap(a,b):
    """0=disjoint normalized profiles, 1=identical; NOT crosstalk."""
    if not np.isfinite(a).all() or not np.isfinite(b).all() or a.sum()<=0 or b.sum()<=0:
        return None
    return float(np.minimum(a/a.sum(),b/b.sum()).sum())


def write_csv(path,rows):
    if not rows:return
    with path.open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=rows[0]);writer.writeheader();writer.writerows(rows)


def analyze(folder):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    folder=Path(folder);manifest=json.loads((folder/'scan_config.json').read_text())
    data=manifest['physical_config'];tiles=manifest['tiles'];cases=data['cases']
    slope=data['optics']['normal_slope'];nx=1/math.sqrt(1+slope*slope)
    n=data['optics']['ior'];t=data['optics']['thickness_mm']
    a=data['led_to_vertex_mm']-(t+data.get('rear_acrylic_mm',0))*(1-1/n)
    q=data['screen_from_vertex_mm']/n
    period=data['optics']['pitch_mm']*(1+q/a)
    metrics=[];overlaps=[];lines={};complete=[]
    colors=['tab:blue','tab:orange','tab:green','tab:red']
    # One display scale across all tiles/cases/phases. Numerical data are not clipped.
    references=[]
    for tile in tiles:
        for case in cases:
            for phase in range(4):
                path=field_path(folder,tile,case,phase)
                if valid_field(path,(tile['pixels'][1],tile['pixels'][0])):
                    references.append(float(np.quantile(np.load(path,mmap_mode='r'),.995)))
    display_max=max(references,default=0.) or 1.
    for tile in tiles:
        all_fields=[]
        for case in cases:
            ps=[]
            for phase in range(4):
                path=field_path(folder,tile,case,phase)
                if not valid_field(path,(tile['pixels'][1],tile['pixels'][0])):break
                im=np.load(path);all_fields.append((case,phase,im))
                u,p,count=folded_profile(im,tile['size_mm'],slope,period,128)
                # Restore world-coordinate phase rather than independently resetting each tile.
                x,y=tile['center_mm'];offset=nx*(x+slope*y)
                target=(u-offset)%period
                p=np.interp(target,np.r_[u-period,u,u+period],np.tile(p,3))
                ps.append(p)
                stats=peak_stats(p,period,nx)
                coarse=tile['size_mm'][0]/tile['pixels'][0]>.01
                if coarse:
                    stats['peak_normal_mm']=None;stats['width_horizontal_mm']=None
                metrics.append(dict(tile=tile['id'],region=tile['region'],x_mm=x,y_mm=y,
                                    case=case,phase=phase,mean_field=float(im.mean()),
                                    nonzero_fraction=float(np.count_nonzero(im)/im.size),
                                    quality_flag='coarse_pixels' if coarse else 'not_convergence_validated',**stats))
                hx,hp,hc=horizontal_profile(im,tile['size_mm'],slope)
                lines.setdefault((case,phase,tile['region']),[]).append((hx+x+slope*y,hp))
            if len(ps)==4:
                for i,j in itertools.combinations(range(4),2):
                    overlaps.append(dict(tile=tile['id'],region=tile['region'],x_mm=tile['center_mm'][0],
                                         case=case,phase_a=i,phase_b=j,
                                         normalized_profile_overlap=None if coarse else shape_overlap(ps[i],ps[j])))
        if len(all_fields)==len(cases)*4:
            complete.append(tile['id'])
            vmax=display_max
            fig,axes=plt.subplots(len(cases),4,figsize=(12,4),squeeze=False,layout='constrained')
            for case,phase,im in all_fields:
                plt.imsave(folder/tile['id']/f'{case}_phase{phase}.png',im[::-1,::-1],
                           vmin=0,vmax=vmax,cmap='viridis')
                ax=axes[cases.index(case),phase]
                x,y=tile['center_mm'];w,h=tile['size_mm']
                ax.imshow(im[::-1,::-1],extent=[x-w/2,x+w/2,y-h/2,y+h/2],origin='lower',
                          aspect='auto',vmin=0,vmax=vmax,cmap='viridis')
                ax.set_title(f'{case}: phase {phase}');ax.set_xlabel('World x (mm)')
            fig.suptitle(tile['id']+'; common display scale across the entire scan')
            fig.savefig(folder/tile['id']/'fields.png',dpi=140);plt.close(fig)
    write_csv(folder/'metrics.csv',metrics);write_csv(folder/'overlap.csv',overlaps)
    regions=list(dict.fromkeys(t['region'] for t in tiles))
    if lines:
        fig,axes=plt.subplots(len(cases),len(regions),figsize=(6*len(regions),3.5*len(cases)),
                              squeeze=False,layout='constrained')
        for row,case in enumerate(cases):
            for col,region in enumerate(regions):
                ax=axes[row,col]
                for phase in range(4):
                    parts=sorted(lines.get((case,phase,region),[]),key=lambda p:p[0][0])
                    if parts:
                        xx=np.concatenate([np.r_[v[0],np.nan] for v in parts])
                        yy=np.concatenate([np.r_[v[1],np.nan] for v in parts])
                        ax.plot(xx,yy,color=colors[phase],label=f'phase {phase}',lw=.7)
                ax.set_title(f'{case} / {region}');ax.set_xlabel('World x at y=0 (mm)')
                ax.set_ylabel('Relative illumination');ax.legend(ncol=2);ax.grid(alpha=.2)
        fig.savefig(folder/'stitched_profiles.png',dpi=150);plt.close(fig)
    if metrics:
        fig,axes=plt.subplots(2,len(cases),figsize=(6*len(cases),7),squeeze=False,layout='constrained')
        for col,case in enumerate(cases):
            for phase in range(4):
                for reg in regions:
                    rr=sorted([r for r in metrics if r['case']==case and r['phase']==phase
                               and r['region']==reg and r['width_horizontal_mm'] is not None],key=lambda r:r['x_mm'])
                    if rr:axes[0,col].plot([r['x_mm'] for r in rr],[r['width_horizontal_mm'] for r in rr],
                                          '.-',ms=3,color=colors[phase],label=f'phase {phase}' if reg==regions[0] else None)
            axes[0,col].set_title(case+' / estimated dominant-peak width')
            axes[0,col].set_ylabel('Horizontal width (mm)')
            if axes[0,col].lines:axes[0,col].legend(ncol=2)
            for pair in itertools.combinations(range(4),2):
                for reg in regions:
                    rr=sorted([r for r in overlaps if r['case']==case and r['region']==reg
                               and (r['phase_a'],r['phase_b'])==pair
                               and r['normalized_profile_overlap'] is not None],key=lambda r:r['x_mm'])
                    if rr:axes[1,col].plot([r['x_mm'] for r in rr],[r['normalized_profile_overlap'] for r in rr],
                                          '.-',ms=3,label=f'{pair[0]}/{pair[1]}' if reg==regions[0] else None)
            axes[1,col].set_title('Normalized shape overlap (not LCD crosstalk)')
            axes[1,col].set_ylim(0,1)
            if axes[1,col].lines:axes[1,col].legend(ncol=3)
            for row in range(2):
                axes[row,col].set_xlabel('Tile center World x (mm)');axes[row,col].grid(alpha=.2)
        fig.savefig(folder/'comparison_metrics.png',dpi=150);plt.close(fig)
    report=dict(complete_tiles=len(complete),planned_tiles=len(tiles),
                integrator=manifest['integrator'],spp=manifest['spp'],
                display_max=display_max,
                pixel_mm=tiles[0]['size_mm'][0]/tiles[0]['pixels'][0],
                warning='Spatial profile overlap and smoothed dominant-peak widths only. '
                        'Not LCD/observer crosstalk or converged PSF. '
                        'Backward path estimator differs from previous ptracer runs; '
                        'absolute values and sampling quality need convergence checks. '
                        'PNG display scaling is common across all saved tiles, cases and phases. '
                        'The .995-quantile display scale may clip bright outliers; NPY is unchanged.')
    (folder/'analysis_summary.json').write_text(json.dumps(report,indent=2)+'\n')
    with zipfile.ZipFile(folder/'summary_bundle.zip','w',zipfile.ZIP_DEFLATED) as bundle:
        for name in ['scan_config.json','analysis_summary.json','metrics.csv','overlap.csv',
                     'comparison_metrics.png','stitched_profiles.png','led_layout.json']:
            if (folder/name).is_file():bundle.write(folder/name,name)
    print(json.dumps(report,indent=2))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=ROOT/'configs/current.json')
    parser.add_argument('--variant',choices=['cuda_ad_rgb','llvm_ad_rgb','scalar_rgb'],default='cuda_ad_rgb')
    parser.add_argument('--spp',type=int,default=64)
    parser.add_argument('--samples-per-pass',type=int,default=4)
    parser.add_argument('--pixels',type=int,default=2048)
    parser.add_argument('--tile-mm',type=float,default=8.)
    parser.add_argument('--band-mm',type=float,default=200.)
    parser.add_argument('--region',choices=['left','center','right'],action='append')
    parser.add_argument('--y',type=float,default=0.)
    parser.add_argument('--limit-tiles',type=int)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--resume',type=Path)
    parser.add_argument('--plan-only',action='store_true')
    parser.add_argument('--analyze-only',type=Path)
    args=parser.parse_args(argv)
    if args.analyze_only:
        analyze(args.analyze_only);return 0
    if args.spp<1 or args.samples_per_pass<1 or (args.limit_tiles is not None and args.limit_tiles<1):
        parser.error('spp, samples-per-pass and limit-tiles must be positive')
    try:
        data,cfg=load_config(args.config)
        regions=args.region or ['center','left','right']
        if len(regions)!=len(set(regions)):raise ValueError('Duplicate regions')
        tiles=make_tiles(data,regions,args.tile_mm,args.pixels,args.y,args.limit_tiles,args.band_mm)
    except (ValueError,OSError,KeyError) as exc:parser.error(str(exc))
    data['render']['variant']=args.variant
    settings=dict(physical_config=data,tiles=tiles,integrator='path',spp=args.spp,
                  samples_per_pass=args.samples_per_pass,version=2)
    if args.resume:
        folder=args.resume
        saved=json.loads((folder/'scan_config.json').read_text())
        if settings!=saved:
            parser.error('Resume settings differ. Repeat the original options or choose a new output.')
    else:
        folder=args.output or ROOT/'results'/('scan_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
        if folder.exists() and any(folder.iterdir()):parser.error('Output is not empty; use --resume')
    print(f'{len(tiles)} tiles; {len(data["cases"])*4*len(tiles)} jobs; '
          f'pixel {tiles[0]["size_mm"][0]/args.pixels:.6f} mm; spp {args.spp}; path integrator')
    print('Each band covers the four-LED illumination envelope approximately; full optics and all LEDs remain unchanged.')
    print(f'Output: {folder.resolve()}',flush=True)
    if args.plan_only:return 0
    import mitsuba as mi
    import drjit as dr
    mi.set_variant(args.variant);dr.set_thread_count(data['render']['threads'])
    folder.mkdir(parents=True,exist_ok=True)
    (folder/'scan_config.json').write_text(json.dumps(settings,indent=2)+'\n')
    (folder/'led_layout.json').write_text(json.dumps([dict(index=i,phase=p,horizontal_intercept_mm=x) for i,p,x in led_layout(data,cfg)],indent=2)+'\n')
    mesh=folder/'lens.ply'
    if not mesh.exists():
        v,f=lens_coordinates(lens_mesh_config(data,cfg),data.get('lens_outline_mm'))
        write_binary_ply(mesh,v,f)
    total=len(tiles)*len(data['cases'])*4;done=0
    for case in data['cases']:
        for phase in range(4):
            pending=[t for t in tiles if not valid_field(field_path(folder,t,case,phase),
                                                       (t['pixels'][1],t['pixels'][0]))]
            done+=len(tiles)-len(pending)
            if not pending:continue
            local=tile_data(data,pending[0]);local['render']['preview']['spp']=min(args.samples_per_pass,args.spp)
            obj=scene_dict(mi,local,cfg,mesh,phase,case,'preview')
            obj['integrator']={'type':'path','max_depth':data['render']['max_depth'],'hide_emitters':True}
            scene=mi.load_dict(obj);params=mi.traverse(scene)
            for tile in pending:
                x,y=tile['center_mm'];z=data['screen_from_vertex_mm'];dist=min(1.,z*.5)
                unit=.001*data['render']['scene_scale']
                params['sensor.to_world']=mi.ScalarTransform4f.look_at(
                    origin=[x*unit,y*unit,(z-dist)*unit],target=[x*unit,y*unit,z*unit],up=[0,1,0])
                params.update()
                started=time.monotonic();acc=np.zeros((tile['pixels'][1],tile['pixels'][0]),np.float64)
                remaining=args.spp;part=0
                while remaining:
                    batch=min(remaining,args.samples_per_pass)
                    seed=(data['render']['seed']+phase*1000003+tile['index']*1009+part)%(2**32)
                    rgb=np.asarray(mi.render(scene,spp=batch,seed=seed))
                    acc+=rgb.mean(axis=2)*math.pi*batch
                    remaining-=batch;part+=1
                image=(acc/args.spp).astype(np.float32)
                if not np.isfinite(image).all() or (image<0).any():raise ValueError('Invalid rendered field')
                path=field_path(folder,tile,case,phase);path.parent.mkdir(exist_ok=True)
                temporary=path.with_suffix('.tmp')
                with temporary.open('wb') as handle:np.save(handle,image)
                temporary.replace(path);done+=1
                (folder/'progress.json').write_text(json.dumps(dict(completed=done,total=total,last_file=str(path))))
                print(f'[{done}/{total}] {tile["id"]} {case} phase{phase}: '
                      f'{time.monotonic()-started:.1f}s; mean={image.mean():.6g}',flush=True)
            del params,scene
            if args.variant.startswith('cuda'):
                dr.sync_thread();dr.flush_malloc_cache()
    analyze(folder)
    print(f'Complete: {folder.resolve()}');return 0


if __name__=='__main__':
    raise SystemExit(main())
