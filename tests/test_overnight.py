import copy,json
from pathlib import Path
import pytest
from simulate import load_config
from overnight_model import build_plan,stage_args,complete,atomic_json

CONFIG=Path(__file__).resolve().parents[1]/'configs/rebuilt_v2.json'

def test_overnight_covers_full_width_three_heights_and_keeps_physics():
 d,c=load_config(CONFIG);before=copy.deepcopy(d);plan=build_plan(d,pass_spp=1)
 assert d==before
 assert sum(s['jobs'] for s in plan['stages'])==1728
 full=[s for s in plan['stages'] if s.get('mode')=='full']
 assert sorted(s['y'] for s in full)==[-100,0,100]
 assert all(s['jobs']==552 and s['spp']==512 for s in full)
 sources=next(s for s in plan['stages'] if s['kind']=='single')
 assert sources['leds']==[3,7,11,15] and sources['seeds']==[17,29]
 assert any(s['scale']==10000 for s in plan['stages'])
 assert sum(s['expected_bytes'] for s in plan['stages'])<4*2**30


def test_stage_resume_args_and_atomic_metadata(tmp_path):
 d,c=load_config(CONFIG);plan=build_plan(d);stage=plan['stages'][0]
 args=stage_args(stage,tmp_path/'cfg.json',tmp_path/'stage',plan)
 assert '--output' in args and '--band-mm' in args and '--region' in args
 folder=tmp_path/'stage';folder.mkdir();(folder/'scan_config.json').write_text('{}')
 assert '--resume' in stage_args(stage,tmp_path/'cfg.json',folder,plan)
 assert not complete(stage,folder)
 atomic_json(tmp_path/'state.json',{'status':'done'})
 assert json.loads((tmp_path/'state.json').read_text())=={'status':'done'}
 assert not (tmp_path/'state.tmp').exists()


def test_single_diagnostic_resume_preserves_arrays(tmp_path):
 pytest.importorskip('mitsuba')
 from single_led_diagnostic import main
 import hashlib
 args=['--variant','scalar_rgb','--pixels','16','--spp','1','--led','9','--seed','17','--samples-per-pass','1']
 assert main([*args,'--output',str(tmp_path)])==0
 before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.glob('*.npy')}
 assert len(before)==2
 assert main([*args,'--resume',str(tmp_path)])==0
 assert before=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.glob('*.npy')}
