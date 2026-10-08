import pathlib,json,hashlib,time,datetime
D=pathlib.Path(__file__).parent;R=pathlib.Path('/private/tmp/sberindex-official-laws-20261007')
files=['docs/CONTEST_SUBMISSIONS_2026-10-08.json']
for directory in ['shock-radar/runs/National_equal_information_20261006','economic-atlas/runs/Consumer_closeout_20261006','economic-atlas/runs/Consumer_mechanisms_20261007']:
 for n in ['predictions.parquet','metrics.json','protocol.json','manifest.json']:
  files.append(directory+'/'+n)
j={'frozen_at_UTC':datetime.datetime.now(datetime.timezone.utc).isoformat(),'original_monotonic_anchor':time.monotonic(),'scope':'Saved national h12 pilot720 rows/120series and saved consumer headline h1/h3 supported9234 exact keys each; FULL table key/row coverage audited; no new CI/bootstrap/model/window','limits':{'whole_seconds':300,'RSS_bytes':1073741824,'output_bytes':134217728,'CPU_threads':1},'inputs':{n:{'SHA':hashlib.sha256((R/n).read_bytes()).hexdigest(),'bytes':(R/n).stat().st_size}for n in files},'schema_only_before_numeric_code_freeze':True,'scientific_pass':False,'resume':False,'actual_model_calls':0}
(D/'PROTOCOL.json').write_text(json.dumps(j,indent=2)+'\n')
