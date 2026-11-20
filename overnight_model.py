r"""Sequential GPU overnight suite. Physical dimensions are not changed.
Windows: .\.venv\Scripts\python.exe overnight_model.py
Repeat the same command to resume. --plan-only does not render or write files.
"""
from __future__ import annotations
import argparse,atexit,csv,json,os,subprocess,sys,zipfile
from pathlib import Path
from datetime import datetime
import numpy as np
from simulate import ROOT,load_config
from scan_tiles import make_tiles,make_spot_tiles,valid_field


def atomic_json(path,data):
 tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8');tmp.replace(path)


def build_plan(base,variant='cuda_ad_rgb',pass_spp=4,smoke=False):
 stages=[]
 for name,y in [('full_width_center',0.),('full_width_upper',100.),('full_width_lower',-100.)]:
  tiles=make_tiles(base,['center'],tile_mm=8.,pixels=2048,y=y,band_mm=base['roi_mm'][0])
  stages.append(dict(name=name,kind='scan',mode='full',y=y,seed=17,scale=1000.,spp=512,pixels=2048,tile_mm=8.,jobs=len(tiles)*8,expected_bytes=len(tiles)*8*2048*256*4))
 local=[]
 for seed in [17,29]:
  local.append(dict(name=f'local_seed{seed}',kind='scan',mode='spots',y=0.,seed=seed,scale=1000.,spp=1024,pixels=512,tile_mm=2.,jobs=24,expected_bytes=24*512*64*4))
 local.append(dict(name='local_scale10000',kind='scan',mode='center',y=0.,seed=17,scale=10000.,spp=1024,pixels=512,tile_mm=2.,jobs=8,expected_bytes=8*512*64*4))
 local.append(dict(name='phase3_individual_sources',kind='single',leds=[3,7,11,15],seeds=[17,29],seed=17,scale=1000.,spp=1024,pixels=512,jobs=16,expected_bytes=16*512*64*4))
 # Get one full-width row first, then diagnostic evidence, then the other heights.
 stages=[stages[0],*local,*stages[1:]]
 if smoke:
  stages=[dict(name='smoke_scan',kind='scan',mode='center',y=0.,seed=17,scale=1000.,spp=1,pixels=16,tile_mm=2.,jobs=8,expected_bytes=8*16*2*4),
          dict(name='smoke_source',kind='single',leds=[7],seeds=[17],seed=17,scale=1000.,spp=1,pixels=16,jobs=2,expected_bytes=2*16*2*4)]
 return dict(suite_version=1,physical_config=base,variant=variant,samples_per_pass=pass_spp,smoke=smoke,stages=stages)


def stage_args(stage,config,folder,plan):
 args=[sys.executable,'-u',str(ROOT/('single_led_diagnostic.py' if stage['kind']=='single' else 'scan_tiles.py')),
       '--config',str(config),'--variant',plan['variant'],'--spp',str(stage['spp']),'--pixels',str(stage['pixels']),
       '--samples-per-pass',str(plan['samples_per_pass'])]
 if stage['kind']=='single':
  for led in stage['leds']:args+=['--led',str(led)]
  for seed in stage['seeds']:args+=['--seed',str(seed)]
  marker='diagnostic_config.json'
 else:
  args+=['--tile-mm',str(stage['tile_mm'])]
  if stage['mode']=='full':args+=['--region','center','--band-mm',str(plan['physical_config']['roi_mm'][0]),'--y',str(stage['y'])]
  else:
   for x in ([0.,-250.,250.] if stage['mode']=='spots' else [0.]):args+=['--spot-x',str(x)]
  marker='scan_config.json'
 args+=['--resume' if (folder/marker).exists() else '--output',str(folder)]
 return args


def complete(stage,folder):
 try:
  if stage['kind']=='single':
   names=[folder/f'{case}_led{led:02d}_spp{stage["spp"]}_seed{seed}.npy' for case in ['baffles','mask_baffles'] for led in stage['leds'] for seed in stage['seeds']]
  else:
   m=json.loads((folder/'scan_config.json').read_text());names=[folder/t['id']/f'{case}_phase{phase}.npy' for t in m['tiles'] for case in m['physical_config']['cases'] for phase in range(4)]
  chart='profiles.png' if stage['kind']=='single' else 'analysis_summary.json'
  return len(names)==stage['jobs'] and (folder/'metrics.csv').exists() and (folder/chart).exists() and all(valid_field(p,(stage['pixels']//8,stage['pixels'])) for p in names)
 except (OSError,ValueError,KeyError):return False


def collect(root,plan,state):
 summary=[]
 for stage in plan['stages']:
  path=root/stage['name']/'metrics.csv'
  if not path.exists():continue
  with path.open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
  if stage['kind']=='scan':
   for case in ['baffles','mask_baffles']:
    for phase in range(4):
     r=[x for x in rows if x['case']==case and int(x['phase'])==phase];w=[float(x['width_horizontal_mm']) for x in r if x.get('width_horizontal_mm')]
     if r:summary.append(dict(stage=stage['name'],case=case,phase=phase,fields=len(r),mean_field=float(np.mean([float(x['mean_field']) for x in r])),median_estimated_width_mm=float(np.median(w)) if w else '',warning='spatial optical estimates, not measured crosstalk'))
 if summary:
  with (root/'suite_summary.csv').open('w',newline='',encoding='utf-8-sig') as f:
   wr=csv.DictWriter(f,fieldnames=list(summary[0]));wr.writeheader();wr.writerows(summary)
 # Attribute phase3 power to each LED. Same fixed irradiance receiver; not observer crosstalk.
 source=root/'phase3_individual_sources'/'metrics.csv'
 if source.exists():
  with source.open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
  result=[]
  for case in ['baffles','mask_baffles']:
   for seed in [17,29]:
    group=[r for r in rows if r['case']==case and int(r['seed'])==seed];total=sum(float(r['mean']) for r in group)
    for r in group:result.append(dict(case=case,seed=seed,led=r['led'],mean_field=r['mean'],fraction_of_source_sum=float(r['mean'])/total if total else '',warning='fraction of local illumination, not crosstalk'))
  if result:
   with (root/'phase3_source_shares.csv').open('w',newline='',encoding='utf-8-sig') as f:
    wr=csv.DictWriter(f,fieldnames=list(result[0]));wr.writeheader();wr.writerows(result)
 checks=[]
 for label,reference,other,tiles in [('seed_17_vs_29','local_seed17','local_seed29',range(3)),('scale_1000_vs_10000','local_seed17','local_scale10000',[0])]:
  for tile in tiles:
   for case in ['baffles','mask_baffles']:
    for phase in range(4):
     filename=f'spot_{tile:03d}/{case}_phase{phase}.npy';pa=root/reference/filename;pb=root/other/filename
     if not (pa.exists() and pb.exists()):continue
     va=np.load(pa);vb=np.load(pb);mean_a=float(va.mean());mean_b=float(vb.mean());den=max(mean_a,mean_b)
     relative=abs(mean_a-mean_b)/den if den else 0.
     checks.append(dict(check=label,tile=tile,case=case,phase=phase,mean_a=mean_a,mean_b=mean_b,relative_mean_difference=relative,review_mean_difference_over_5pct=relative>.05,warning='mean agreement is not a full spatial-convergence test'))
 if checks:
  with (root/'numerical_sampling_checks.csv').open('w',newline='',encoding='utf-8-sig') as f:
   wr=csv.DictWriter(f,fieldnames=list(checks[0]));wr.writeheader();wr.writerows(checks)
 target=root/'overnight_summary.zip';temporary=root/'overnight_summary.tmp'
 with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as z:
  for f in root.rglob('*'):
   if not f.is_file() or f.name.startswith('overnight_summary'):continue
   rel=f.relative_to(root);is_full=any(p.startswith('full_width_') for p in rel.parts)
   if f.suffix in ('.json','.csv','.log') or f.name in ['comparison_metrics.png','stitched_profiles.png','profiles.png'] or (f.suffix=='.npy' and not is_full):
    z.write(f,rel)
 temporary.replace(target)


def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--config',type=Path,default=ROOT/'configs/rebuilt_v2.json')
 p.add_argument('--output',type=Path,default=ROOT/'results/overnight_v2')
 p.add_argument('--variant',choices=['cuda_ad_rgb','llvm_ad_rgb','scalar_rgb'],default='cuda_ad_rgb')
 p.add_argument('--samples-per-pass',type=int,default=1)
 p.add_argument('--plan-only',action='store_true')
 p.add_argument('--smoke-test',action='store_true',help='Only tiny execution tests; not usable as optical evidence')
 a=p.parse_args(argv)
 try:
  base,c=load_config(a.config)
  if a.samples_per_pass<1:raise ValueError('samples-per-pass must be positive')
  if base['roi_mm']!=[546,312] or base['led_array']['count']!=19:raise ValueError('This suite expects the agreed 546x312 mm / 19 LED model')
  if base['render']['origin_mode']!='view_center':raise ValueError('view_center origin required')
 except (OSError,ValueError,KeyError) as exc:p.error(str(exc))
 plan=build_plan(base,a.variant,a.samples_per_pass,a.smoke_test)
 print('Sequential stages; no physical dimensions changed.',flush=True)
 for stage in plan['stages']:print(f"{stage['name']}: {stage['jobs']} jobs, {stage['spp']} spp",flush=True)
 print(f"TOTAL {sum(s['jobs'] for s in plan['stages'])} jobs; raw arrays about {sum(s['expected_bytes'] for s in plan['stages'])/2**30:.2f} GiB + images/lens files. Output: {a.output.resolve()}",flush=True)
 if a.plan_only:return 0
 if os.name=='nt':
  import ctypes
  ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
  atexit.register(ctypes.windll.kernel32.SetThreadExecutionState,0x80000000)
 root=a.output;root.mkdir(parents=True,exist_ok=True);manifest=root/'overnight_plan.json'
 if manifest.exists():
  if json.loads(manifest.read_text(encoding='utf-8'))!=plan:p.error('Existing overnight plan differs. Use a new output folder or repeat original options.')
 else:
  if any(root.iterdir()):p.error('Output folder is not empty and has no overnight plan')
  atomic_json(manifest,plan)
 configs=root/'configs';configs.mkdir(exist_ok=True)
 state={'started_or_resumed_at':datetime.now().isoformat(),'stages':{},'note':'Read stage status; summary ZIP can contain partial results.'}
 process=None
 try:
  for stage in plan['stages']:
   name=stage['name'];folder=root/name
   if complete(stage,folder):state['stages'][name]={'status':'complete','reused':True};atomic_json(root/'overnight_status.json',state);print('Reusing complete stage:',name,flush=True);continue
   d=json.loads(json.dumps(base));d['render'].update(seed=stage['seed'],scene_scale=stage['scale'],variant=a.variant)
   config=configs/(name+'.json');atomic_json(config,d)
   args=stage_args(stage,config,folder,plan)
   state['stages'][name]={'status':'running','command':args};atomic_json(root/'overnight_status.json',state)
   with (root/(name+'.log')).open('a',encoding='utf-8') as log:
    log.write('\nRESUME/START '+datetime.now().isoformat()+'\n');log.flush()
    env=os.environ.copy();env['PYTHONUNBUFFERED']='1';env['PYTHONIOENCODING']='utf-8'
    print('Starting',name,flush=True)
    process=subprocess.Popen(args,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',env=env)
    for line in process.stdout:print(line,end='',flush=True);log.write(line);log.flush()
    rc=process.wait();process=None
   ok=rc==0 and complete(stage,folder)
   state['stages'][name]={'status':'complete' if ok else 'failed','exit_code':rc};atomic_json(root/'overnight_status.json',state)
   collect(root,plan,state)
   if not ok:print('Stage failed; retaining data and continuing:',name,flush=True)
 except KeyboardInterrupt:
  if process is not None:
   process.terminate()
   try:process.wait(timeout=15)
   except subprocess.TimeoutExpired:process.kill();process.wait()
  state['interrupted']=True;atomic_json(root/'overnight_status.json',state);collect(root,plan,state)
  print('Interrupted. Repeat the same command to resume.',flush=True);return 130
 collect(root,plan,state)
 done=len(state['stages'])==len(plan['stages']) and all(s['status']=='complete' for s in state['stages'].values())
 print('ALL STAGES COMPLETE' if done else 'INCOMPLETE: check overnight_status.json and logs',flush=True)
 print('Send:',(root/'overnight_summary.zip').resolve(),flush=True)
 return 0 if done else 1

if __name__=='__main__':raise SystemExit(main())
