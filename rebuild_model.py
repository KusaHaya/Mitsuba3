r"""Rebuilt optical model, small GPU scans. Default: 8 central jobs, not a full display render.
Windows: .\.venv\Scripts\python.exe rebuild_model.py
All three positions: .\.venv\Scripts\python.exe rebuild_model.py --all-positions
"""
import argparse,json,zipfile
from pathlib import Path
from datetime import datetime
from simulate import ROOT,load_config
from scan_tiles import main as scan,make_spot_tiles


def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--config',type=Path,default=ROOT/'configs/rebuilt_v2.json')
 p.add_argument('--all-positions',action='store_true')
 p.add_argument('--variant',choices=['cuda_ad_rgb','llvm_ad_rgb','scalar_rgb'],default='cuda_ad_rgb')
 p.add_argument('--spp',type=int,default=256)
 p.add_argument('--samples-per-pass',type=int,default=4)
 p.add_argument('--pixels',type=int,default=512)
 p.add_argument('--output',type=Path)
 p.add_argument('--resume',type=Path)
 p.add_argument('--plan-only',action='store_true')
 a=p.parse_args(argv)
 try:
  d,c=load_config(a.config)
  if d['render']['scene_scale']<1000 or d['render']['origin_mode']!='view_center':raise ValueError('Rebuilt model requires scene_scale>=1000 and view_center origin')
  if d['cases']!=['baffles','mask_baffles']:raise ValueError('Rebuilt comparison requires baffles and mask_baffles')
  if a.spp<1 or a.samples_per_pass<1:raise ValueError('Sampling counts must be positive')
  centers=[0.,-250.,250.] if a.all_positions else [0.]
  tiles=make_spot_tiles(d,centers,2.,a.pixels)
 except (ValueError,OSError,KeyError) as exc:p.error(str(exc))
 print(json.dumps(dict(model=d.get('model_revision'),led_count=d['led_array']['count'],phase_counts=[sum((i+d['led_array'].get('first_phase',0))%4==k for i in range(d['led_array']['count'])) for k in range(4)],
                      fields=[t['center_mm'] for t in tiles],size_mm=[2.,.25],jobs=len(tiles)*8,pixel_mm=2/a.pixels,spp=a.spp,
                      physical_screen_mm=d['screen_from_vertex_mm'],scene_scale=d['render']['scene_scale'],origin=d['render']['origin_mode']),indent=2),flush=True)
 folder=a.resume or a.output or ROOT/'results'/('rebuilt_v2_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
 args=['--config',str(a.config),'--variant',a.variant,'--spp',str(a.spp),'--samples-per-pass',str(a.samples_per_pass),'--pixels',str(a.pixels),'--tile-mm','2']
 for x in centers:args+=['--spot-x',str(x)]
 if a.plan_only:args+=['--plan-only','--output',str(folder)]
 elif a.resume:args+=['--resume',str(folder)]
 else:args+=['--output',str(folder)]
 result=scan(args)
 if a.plan_only or result:return result
 # Include all original arrays: only 8 or 24 small fields, unlike the previous huge scan.
 bundle=folder/'rebuilt_results.zip'
 with zipfile.ZipFile(bundle,'w',zipfile.ZIP_DEFLATED) as z:
  for f in folder.rglob('*'):
   if f.is_file() and f.suffix in ('.json','.npy','.png','.csv'):z.write(f,f.relative_to(folder))
 print('Send:',bundle.resolve());return 0

if __name__=='__main__':raise SystemExit(main())
