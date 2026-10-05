#!/usr/bin/env python3
"""Verify and restore five frozen input snapshots from the owner's case ZIP.

No network or credentials. Strict whole-archive and per-file SHA, allowlisted
names and size limits. Existing different files are never overwritten.
"""
from pathlib import Path
import argparse,hashlib,json,zipfile,tempfile,os

ROOT=Path(__file__).resolve().parents[1]
DEFAULTS={
 '8_consumption.parquet':('raw','data/raw/sberindex-data-sense-2025/8_consumption.parquet'),
 'predictions-r9.parquet':('r9','data/frozen/radar/predictions-r9.parquet'),
 'predictions-pilot.parquet':('pilot','data/frozen/radar/predictions-pilot.parquet'),
 'municipal-dictionary.parquet':('dictionary','data/frozen/radar/municipal-dictionary.parquet'),
 'national-consumer-spending.parquet':('national','data/raw/sberindex-national-20261005/consumer-spending.parquet')}

def sha_bytes(value):return hashlib.sha256(value).hexdigest()

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--bundle',type=Path,required=True)
 for name,(key,default) in DEFAULTS.items():p.add_argument('--'+key,type=Path,default=ROOT/default)
 a=p.parse_args();manifest=json.loads((ROOT/'data/frozen/radar/bundle-manifest.json').read_text())
 if a.bundle.stat().st_size!=manifest['bytes'] or sha_bytes(a.bundle.read_bytes())!=manifest['sha256']:raise ValueError('Frozen archive SHA/size mismatch')
 expected={'inputs/'+name for name in DEFAULTS};verified={}
 with zipfile.ZipFile(a.bundle) as z:
  items=z.infolist()
  if len(items)!=len(expected) or {i.filename for i in items}!=expected:raise ValueError('Unexpected or duplicate archive members')
  if sum(i.file_size for i in items)>32*1024*1024:raise ValueError('Archive input size limit exceeded')
  for i in items:
   value=z.read(i);name=Path(i.filename).name
   if sha_bytes(value)!=manifest['contents'][name]:raise ValueError('Frozen member SHA mismatch')
   key,_=DEFAULTS[name];dest=getattr(a,key)
   if dest.exists() and sha_bytes(dest.read_bytes())!=manifest['contents'][name]:raise ValueError('Existing different input; choose new destination: '+str(dest))
   verified[name]=(dest,value)
 written=0
 for name,(dest,value) in verified.items():
  if dest.exists():continue
  dest.parent.mkdir(parents=True,exist_ok=True)
  with tempfile.NamedTemporaryFile(dir=dest.parent,suffix='.part',delete=False) as f:
   temporary=Path(f.name);f.write(value)
  try:
   temporary.chmod(0o444)
   # Avoid overwriting an input created by another preparer after the initial check.
   os.link(temporary,dest);written+=1
  finally:temporary.unlink(missing_ok=True)
 print(json.dumps({'verified_archive':True,'verified_inputs':len(verified),'written':written,'existing_inputs_preserved':len(verified)-written}))
if __name__=='__main__':main()
