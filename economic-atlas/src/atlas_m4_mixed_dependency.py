"""Explicit prospective dependency authority; M4 bank remains old EVR science.
Trusted root durable launcher sets the SHA-bound descriptor; no launch/model API.
"""
from pathlib import Path
import hashlib, importlib.util, json, math, os
AUTHORITY={'engine':'e69c9a79653fd11c6a5a6866fbf5a251c50acdb60cc6b5cdbe3120998a07f74d','recovery':'fff84fa7adcc51490430fb3fdd06cd98842463fdf39be57c39ddef6f8474b079','guardian':'2d984dbf8c48e297307ca479dcda597c591d12a2848cd96a1bba4e437e2d16a4','validator':'ea104f461512ecfffac5e82ce42f1135c1bf65762032b80f21611eb1216a3b9d','amendment':'516ca1cf068dd420ddbd560a8329c27ca9ab4cc9f582375a770e02bc93ff302e','base_source':'5ad14f6e2df75ac89d2285e3a09c304e7894ce6c42a363334a1d568115c1758b','base_protocol':'fd3133bbda35fb7183908e4c3bd4697f5651962adaf8c0cccf74eb4b15c0dc30'}
MODULES={'engine':'atlas_m1_evd_engine.py','recovery':'atlas_m1_recovery_keys.py','guardian':'atlas_m1_recovery_guardian.py','validator':'atlas_m1_recovery_validate.py'}
TOTAL=77881;END='2026-10-08T13:25:46.854058+00:00'
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def load(path,name):
 spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
def terminal_metadata(t,b):
 if t.get('state')!='FULL_MIXED_RECOVERY_DESCRIPTIVE_VERIFIED_NEEDS_INDEPENDENT_AUDIT' or t.get('authority')!=AUTHORITY:raise ValueError('complete actual mixed M1 terminal required')
 if t.get('owned_lifecycle_tree_empty') is not True or t.get('scientific_pass') is not False or t.get('economic_identity_pass') is not False or type(t.get('source_actions_closed')) is not int or t['source_actions_closed']!=0:raise ValueError('M1 false qualification/owned lifecycle required')
 elapsed=t.get('inclusive_elapsed_seconds')
 if type(elapsed) not in (int,float) or not math.isfinite(elapsed) or not 0<=elapsed<=TOTAL:raise ValueError('original conserved M1 budget required')
 if t.get('continuous_total_resource_pass') is not False or t.get('original_exit_code') is not None:raise ValueError('old coverage/exit unknown retained')
 root=Path(b['recovery_root']).resolve()
 if t.get('budget_record',{}).get('out')!=str(root):raise ValueError('terminal must name exact actual recovery namespace')
 if b.get('authority')!=AUTHORITY or b.get('bank_source_sha256')!=AUTHORITY['base_source'] or b.get('bank_numerical_driver')!='evr' or b.get('mixed_dependency_numerical_driver')!='evd':raise ValueError('explicit bank EVR versus dependency EVD authority')
 if b.get('root_independent_actual_M1_acceptance') is not True:raise ValueError('root actual artifact acceptance pending')
 return True

def actual_acceptance(receipt,binding):
 if receipt.get('state')!='M1_FULL_RECOVERY_INDEPENDENTLY_VERIFIED' or receipt.get('authority')!=AUTHORITY or receipt.get('scientific_pass') is not False:raise ValueError('independent actual full M1 review required')
 for name,count in [('calibration_records',360),('monthly_records',72),('nulls_per_held_or_month',99)]:
  if type(receipt.get(name)) is not int or receipt[name]!=count:raise ValueError('independent full360/72/99 scope required')
 if receipt.get('recovery_root')!=str(Path(binding['recovery_root']).resolve()):raise ValueError('independent review exact recovery root')
 for name in ('global_result_sha256','global_manifest_sha256','calibration_manifest_sha256','replay_manifest_sha256'):
  if receipt.get(name)!=binding[name]:raise ValueError('independent review whole-root and phase manifest links')
 if receipt.get('calibration_result_sha256')!=binding['result_sha256'] or receipt.get('replay_result_sha256')!=binding['replay_result_sha256'] or receipt.get('terminal_sha256')!=binding['terminal_sha256']:raise ValueError('actual independent review must name exact artifacts')
 return True

def check(path,binding=None,admission=lambda:None):
 """Only complete actual output; no synthetic/mock authority in production."""
 admission();path=Path(path).resolve()
 if binding is None:
  descriptor=Path(os.environ['M4_MIXED_DEPENDENCY_BINDING']);digest=os.environ['M4_MIXED_DEPENDENCY_BINDING_SHA']
  if sha(descriptor)!=digest:raise ValueError('explicit descriptor hash mismatch')
  binding=json.loads(descriptor.read_text())
 root=path.parent.parent
 if Path(binding['recovery_root']).resolve()!=root:raise ValueError('descriptor recovery root must contain supplied calibration')
 if Path(binding['calibration_result']).resolve()!=path or binding['result_sha256']!=sha(path) or binding['manifest_sha256']!=sha(path.parent/'manifest.json'):raise ValueError('actual complete calibration descriptor mismatch')
 terminal=Path(binding['terminal']);acceptance=Path(binding['independent_acceptance'])
 if sha(terminal)!=binding['terminal_sha256'] or sha(acceptance)!=binding['independent_acceptance_sha256']:raise ValueError('actual terminal/review hash mismatch')
 for name,artifact in [('global_result_sha256',root/'result.json'),('global_manifest_sha256',root/'manifest.json'),('calibration_manifest_sha256',path.parent/'manifest.json'),('replay_manifest_sha256',root/'replay/manifest.json')]:
  if sha(artifact)!=binding[name]:raise ValueError('actual whole-root/phase artifact SHA mismatch')
 if binding['calibration_manifest_sha256']!=binding['manifest_sha256']:raise ValueError('same calibration manifest binding')
 terminal_metadata(json.loads(terminal.read_text()),binding)
 actual_acceptance(json.loads(acceptance.read_text()),binding)
 here=Path(__file__).parent;repo=here.parents[1]
 for field,name in MODULES.items():
  if sha(here/name)!=AUTHORITY[field]:raise ValueError('actual recovery module authority mismatch')
 protocol=repo/'economic-atlas/protocols/M1_NUMERICAL_RECOVERY_V1.json'
 base=repo/'economic-atlas/protocols/M1_PROSPECTIVE_V1.json'
 if sha(protocol)!=AUTHORITY['amendment'] or sha(base)!=AUTHORITY['base_protocol']:raise ValueError('actual amended/base protocols mismatch')
 keys=load(here/MODULES['recovery'],'m4_actual_recovery_keys');validator=load(here/MODULES['validator'],'m4_actual_publication_validator')
 p=keys.read_protocol(protocol);frozen=json.loads(base.read_text());old,missing=keys.ancestral_records(p,frozen)
 if len(missing)!=26:raise ValueError('exact26 recovery scope')
 result=validator.calibration(path.parent,AUTHORITY,p,frozen,old,admission)
 guardian=load(here/MODULES['guardian'],'m4_actual_recovery_guardian')
 guardian.check_pins()
 replaypath=path.parent.parent/'replay/result.json'
 if sha(replaypath)!=binding['replay_result_sha256']:raise ValueError('exact actual full replay binding')
 engine=load(here/MODULES['engine'],'m4_dependency_metadata_panel')
 ids,_,_,_,inputsha=engine.load_panel(guardian.VIEW,frozen)
 validator.replay(replaypath.parent,AUTHORITY,frozen,sha(path),ids,inputsha,admission)
 guardian.verify_whole(path.parent.parent,AUTHORITY,p,frozen,admission)
 quality={k:result['results'][k]['method_quality'] for k in ('10','20','40')}
 if set(quality.values())!={'FAIL_OR_INCONCLUSIVE_FIXED_CONTROLS'}:raise ValueError('mixed original negative qualification retained')
 return {'result_sha256':sha(path),'manifest_sha256':sha(path.parent/'manifest.json'),'source_sha256':AUTHORITY['engine'],'protocol_sha256':AUTHORITY['amendment'],'actual_dependency_authority':AUTHORITY,'bank_method_source_sha256':AUTHORITY['base_source'],'bank_numerical_driver':'evr','mixed_dependency_numerical_driver':'evd','quality_by_k':quality,'positive_scientific_qualification_allowed':False,'complete_verified_records':True,'terminal_sha256':binding['terminal_sha256'],'independent_acceptance_sha256':binding['independent_acceptance_sha256'],'mixed_old334_new26':True}
