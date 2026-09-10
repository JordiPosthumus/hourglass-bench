#!/usr/bin/env python3
"""Inspect canonical names for existing runs; original records are never rewritten."""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import run_editor
import hardware_records


def inspect(root):
    root=Path(root);runs=[]
    for path in sorted((root/'evaluations').glob('*.json')):
        manifest=json.loads(path.read_text())
        if not manifest.get('id') or 'expected' not in manifest:continue
        identity=run_editor.display(root,manifest)
        hardware=hardware_records.recorded(root,manifest)
        runs.append({'id':manifest['id'],'model_alias':manifest.get('model'),'original_manifest_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                     **identity,'physical_machine_key':hardware.get('machine_key'),'comparison_key':hardware.get('comparison_key',hardware.get('machine_key'))})
    return {'schema_version':1,'effect':'Canonical display overlay only. Original manifests, results and editor history retained.',
            'runs':runs,'needs_details':sum(bool(r['missing'] or r['invalid']) for r in runs)}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parent)
    parser.add_argument('--audit',action='store_true',help='Also save this review under backups/.')
    args=parser.parse_args();report=inspect(args.root)
    if args.audit:
        stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        path=args.root/'backups'/('run-name-migration-'+stamp)/'audit.json';path.parent.mkdir(parents=True)
        path.write_text(json.dumps(report,indent=2)+'\n');report['audit_file']=str(path)
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
