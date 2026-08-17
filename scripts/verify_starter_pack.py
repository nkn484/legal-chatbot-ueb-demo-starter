from __future__ import annotations
import json,re,sys
from pathlib import Path
R=Path(__file__).resolve().parents[1]
REQ=['README_FIRST.md','AGENTS.md','opencode.shineshop.example.json','contracts/source-registry.json','contracts/demo-profile.json','contracts/milestones.json','scripts/demo_gate.py','.opencode/commands/m00-spike.md','.opencode/commands/m09-demo-hardening.md']
PAT=[re.compile(r'(?i)(api[_-]?key|token|secret)\s*[:=]\s*["\']?(sk-[A-Za-z0-9_-]{12,})')]
def main()->int:
    err=[]
    for x in REQ:
        if not (R/x).is_file(): err.append('Missing '+x)
    for x in ['opencode.shineshop.example.json','contracts/source-registry.json','contracts/demo-profile.json','contracts/milestones.json']:
        try: json.loads((R/x).read_text(encoding='utf-8'))
        except Exception as e: err.append(f'Invalid JSON {x}: {e}')
    for p in R.rglob('*'):
        if not p.is_file(): continue
        try: t=p.read_text(encoding='utf-8')
        except UnicodeDecodeError: continue
        for rx in PAT:
            if rx.search(t): err.append('Possible secret in '+str(p.relative_to(R)))
    if err:
        print('STARTER_PACK_VERIFY: FAIL'); [print('- '+e) for e in err]; return 1
    print('STARTER_PACK_VERIFY: PASS'); return 0
if __name__=='__main__': sys.exit(main())
