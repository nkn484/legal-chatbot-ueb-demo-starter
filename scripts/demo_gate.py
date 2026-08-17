from __future__ import annotations
import argparse, json, logging, sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
LOG=logging.getLogger('demo_gate'); VALID={'NOT_STARTED','IN_PROGRESS','AWAITING_APPROVAL','PASS','REJECTED'}
def now()->str: return datetime.now(timezone.utc).isoformat()
def root()->Path: return Path(__file__).resolve().parents[1]
def cp()->Path: return root()/'contracts'/'milestones.json'
def sp()->Path: return root()/'.demo-run'/'state.json'
def load(p:Path)->dict[str,Any]:
    try: return json.loads(p.read_text(encoding='utf-8'))
    except FileNotFoundError as e: raise RuntimeError(f'Missing file: {p}') from e
    except json.JSONDecodeError as e: raise RuntimeError(f'Invalid JSON: {p}: {e}') from e
def save(s:dict[str,Any])->None:
    p=sp(); p.parent.mkdir(parents=True,exist_ok=True); t=p.with_suffix('.tmp'); t.write_text(json.dumps(s,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); t.replace(p)
def initial()->dict[str,Any]:
    m=load(cp())['milestones']; return {'version':1,'created_at':now(),'updated_at':now(),'milestones':{k:{'title':v['title'],'status':'NOT_STARTED','started_at':None,'submitted_at':None,'approved_at':None,'rejected_at':None,'history':[]} for k,v in m.items()}}
def state()->dict[str,Any]:
    if not sp().exists(): raise RuntimeError('Not initialized. Run: python scripts/demo_gate.py init')
    s=load(sp())
    for k,v in s.get('milestones',{}).items():
        if v.get('status') not in VALID: raise RuntimeError(f'Invalid status {k}={v.get("status")}')
    return s
def ent(s:dict[str,Any],m:str)->dict[str,Any]:
    if m not in s['milestones']: raise RuntimeError(f'Unknown milestone: {m}')
    return s['milestones'][m]
def hist(e:dict[str,Any],action:str,by:str|None,note:str|None)->None: e['history'].append({'at':now(),'action':action,'by':by,'note':note})
def init_cmd(a):
    if sp().exists(): LOG.info('Already initialized: %s',sp()); return 0
    save(initial()); LOG.info('Initialized: %s',sp()); return 0
def status_cmd(a):
    s=state(); print(f"{'ID':<5} {'STATUS':<20} TITLE")
    for k,v in s['milestones'].items(): print(f"{k:<5} {v['status']:<20} {v['title']}")
    return 0
def start_cmd(a):
    s=state(); e=ent(s,a.milestone)
    if e['status'] not in {'NOT_STARTED','REJECTED'}: raise RuntimeError(f'{a.milestone} cannot start from {e["status"]}')
    deps=load(cp())['milestones'][a.milestone]['depends_on']; bad=[f'{d}={ent(s,d)["status"]}' for d in deps if ent(s,d)['status']!='PASS']
    if bad: raise RuntimeError('Dependencies are not PASS: '+', '.join(bad))
    e['status']='IN_PROGRESS'; e['started_at']=now(); e['submitted_at']=None; hist(e,'START',a.by,a.note); s['updated_at']=now(); save(s); LOG.info('%s -> IN_PROGRESS',a.milestone); return 0
def submit_cmd(a):
    s=state(); e=ent(s,a.milestone)
    if e['status']!='IN_PROGRESS': raise RuntimeError(f'{a.milestone} must be IN_PROGRESS, got {e["status"]}')
    e['status']='AWAITING_APPROVAL'; e['submitted_at']=now(); hist(e,'SUBMIT',a.by,a.note); s['updated_at']=now(); save(s); LOG.info('%s -> AWAITING_APPROVAL',a.milestone); return 0
def approve_cmd(a):
    s=state(); e=ent(s,a.milestone)
    if e['status']!='AWAITING_APPROVAL': raise RuntimeError(f'{a.milestone} must be AWAITING_APPROVAL, got {e["status"]}')
    e['status']='PASS'; e['approved_at']=now(); hist(e,'APPROVE',a.by,a.note); s['updated_at']=now(); save(s); LOG.info('%s -> PASS',a.milestone); return 0
def reject_cmd(a):
    s=state(); e=ent(s,a.milestone)
    if e['status'] not in {'IN_PROGRESS','AWAITING_APPROVAL'}: raise RuntimeError(f'{a.milestone} cannot reject from {e["status"]}')
    e['status']='REJECTED'; e['rejected_at']=now(); hist(e,'REJECT',a.by,a.note); s['updated_at']=now(); save(s); LOG.info('%s -> REJECTED',a.milestone); return 0
def parser():
    p=argparse.ArgumentParser(description='Lightweight demo milestone gate'); sub=p.add_subparsers(dest='cmd',required=True)
    q=sub.add_parser('init'); q.set_defaults(fn=init_cmd); q=sub.add_parser('status'); q.set_defaults(fn=status_cmd)
    for n,f in [('start',start_cmd),('submit',submit_cmd),('approve',approve_cmd),('reject',reject_cmd)]:
        q=sub.add_parser(n); q.add_argument('milestone'); q.add_argument('--by',default='USER' if n in {'approve','reject'} else None); q.add_argument('--note'); q.set_defaults(fn=f)
    return p
def main()->int:
    a=parser().parse_args()
    try: return int(a.fn(a))
    except RuntimeError as e: LOG.error('%s',e); return 2
if __name__=='__main__':
    logging.basicConfig(level=logging.INFO,format='%(levelname)s %(message)s'); sys.exit(main())
