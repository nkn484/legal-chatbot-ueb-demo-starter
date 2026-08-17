from __future__ import annotations
import argparse, json, logging, sys
from pathlib import Path
LOG=logging.getLogger('prepare_opencode_config')
PH='__SHINE_MODEL_ID__'
def main()->int:
    p=argparse.ArgumentParser(); p.add_argument('--model-id',required=True); p.add_argument('--force',action='store_true'); a=p.parse_args()
    mid=a.model_id.strip()
    if not mid or any(c.isspace() for c in mid): LOG.error('Model ID must be non-empty and contain no whitespace.'); return 2
    root=Path(__file__).resolve().parents[1]; src=root/'opencode.shineshop.example.json'; dst=root/'opencode.json'
    if dst.exists() and not a.force: LOG.error('%s exists; use --force only intentionally.',dst); return 2
    raw=src.read_text(encoding='utf-8')
    if PH not in raw: LOG.error('Template placeholder missing.'); return 2
    data=json.loads(raw.replace(PH,mid))
    if data.get('model')!=f'shineshop/{mid}': LOG.error('Rendered model is inconsistent.'); return 2
    dst.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    LOG.info('Created %s without credentials.',dst); LOG.info("Next: OpenCode /connect -> Other -> provider id 'shineshop'.")
    return 0
if __name__=='__main__':
    logging.basicConfig(level=logging.INFO,format='%(levelname)s %(message)s'); sys.exit(main())
