import importlib.util,pathlib,unittest,tempfile,copy,json,plistlib
from unittest.mock import patch
P=pathlib.Path(__file__).resolve().parents[1]/'economic-atlas/src/atlas_m2m3_full_guardian.py'
s=importlib.util.spec_from_file_location('guardian',P);g=importlib.util.module_from_spec(s);s.loader.exec_module(g)
def bank():
 keys=[dict(seed=s,world=w,mode=m,margin_factor=f) for s in g.SEEDS for w in g.WORLDS for m in g.MODES for f in g.FACTORS]
 return {'runs':[{**k,'m3_sensitivity_counts':{x:{} for x in g.SENS},'selected_k':[3]*24} for k in keys],'regions':[{**k,'regions':[{'month':m} for m in g.MONTHS]} for k in keys],'events':[{**k,'events':[]} for k in keys],'labels':[dict(seed=s,world=w,mode=m,months=g.MONTHS,member_ids=list(range(200)),labels=[[0]*200 for _ in range(24)]) for s in g.SEEDS for w in g.WORLDS for m in g.MODES],'worlds':[dict(seed=s,world=w,cube_shape=[200,24,5],cube_float64_C_order_SHA='a'*64,truth_SHA='b'*64,coordinates_conserved=True if w in ('split','merge') else None) for s in g.SEEDS for w in g.WORLDS],'metrics':dict(n_runs=210,scientific_pass=False,economic_truth_verified=False,acceptance={'status':'FAIL'})}
class Guards(unittest.TestCase):
 def test_full_negative_is_complete(self):g.bank_records(bank())
 def test_full_inconclusive_is_complete(self):
  b=bank();b['metrics']['acceptance']['status']='INCONCLUSIVE';g.bank_records(b)
 def bad(self,fn):
  b=bank();fn(b)
  with self.assertRaises((ValueError,KeyError)):g.bank_records(b)
 def test_missing_config(self):self.bad(lambda b:b['runs'].pop())
 def test_duplicate_config(self):self.bad(lambda b:b['runs'].__setitem__(0,b['runs'][1]))
 def test_missing_mode(self):self.bad(lambda b:b['runs'][0].update(mode='archived'))
 def test_boolean_factor(self):self.bad(lambda b:b['runs'][0].update(margin_factor=True))
 def test_missing_factor(self):self.bad(lambda b:b['runs'][0].update(margin_factor=.5))
 def test_missing_sensitivity(self):self.bad(lambda b:b['runs'][0]['m3_sensitivity_counts'].pop(next(iter(g.SENS))))
 def test_missing_region_month(self):self.bad(lambda b:b['regions'][0]['regions'].pop())
 def test_missing_labels(self):self.bad(lambda b:b['labels'].pop())
 def test_label_month(self):self.bad(lambda b:b['labels'][0]['labels'].pop())
 def test_label_member(self):self.bad(lambda b:b['labels'][0]['labels'][0].pop())
 def test_missing_world(self):self.bad(lambda b:b['worlds'].pop())
 def test_point_redraw(self):self.bad(lambda b:next(x for x in b['worlds'] if x['world']=='split').update(coordinates_conserved=False))
 def test_cube_shape(self):self.bad(lambda b:b['worlds'][0].update(cube_shape=[199,24,5]))
 def test_missing_cube_sha(self):self.bad(lambda b:b['worlds'][0].update(cube_float64_C_order_SHA='z'*64))
 def test_false_science(self):self.bad(lambda b:b['metrics'].update(scientific_pass=True))
 def test_keys_full(self):g.real_records([dict(territory_id=t,month=m) for t in range(1896) for m in g.MONTHS],list(range(1896)))
 def test_keys_duplicate(self):
  rows=[dict(territory_id=t,month=m) for t in range(1896) for m in g.MONTHS];rows[0]=rows[1]
  with self.assertRaises(ValueError):g.real_records(rows,list(range(1896)))
 def test_keys_wrong_mask(self):
  with self.assertRaises(ValueError):g.real_records([dict(territory_id=t,month=m) for t in range(1896) for m in g.MONTHS],list(range(1,1897)))
 def test_all2023(self):
  with self.assertRaises(ValueError):g.calibration({'geometry_version':'geometry-original-scope-v4.0.4','cal_months':[0]})
 def test_no_archive_command(self):
  c=g.commands(pathlib.Path('/view'),pathlib.Path('/out'));self.assertNotIn('--archived-assignments',str(c));self.assertIn('--seed',c[0]);self.assertIn('/out/real/calibration.json',c[1])
 def test_one_use_alternate_output(self):
  with tempfile.TemporaryDirectory() as d,patch.object(g,'LEDGER_ROOT',pathlib.Path(d)/'ledger'):
   key=g.reservation();g.atomic(key,{'out':'a'},True)
   with self.assertRaises(FileExistsError):g.atomic(g.reservation(),{'out':'b'},True)
 def test_bad_ledger_permissions(self):
  with tempfile.TemporaryDirectory() as d,patch.object(g,'LEDGER_ROOT',pathlib.Path(d)):
   pathlib.Path(d).chmod(0o755)
   with self.assertRaises(ValueError):g.reservation()
 def test_low_disk_before_import(self):
  with patch.object(g.shutil,'disk_usage',return_value=type('D',(),{'free':1})()),patch.object(g.time,'monotonic',return_value=2):
   with self.assertRaises(ValueError):g.admission(1,(pathlib.Path('/tmp/fresh'),))
 def test_exhausted_startup(self):
  with patch.object(g.time,'monotonic',return_value=4171):
   with self.assertRaises(ValueError):g.admission(0,(pathlib.Path('/tmp/fresh'),))
 def test_nonfinite_clock(self):
  for v in [True,float('nan'),float('inf')]:
   with self.assertRaises(ValueError):g.finite(v)
 def test_oversize_output(self):
  with patch.object(g.shutil,'disk_usage',return_value=type('D',(),{'free':g.FREE})()),patch.object(g.time,'monotonic',return_value=2),patch.object(g,'size',return_value=g.OUT):
   with self.assertRaises(ValueError):g.admission(1,(pathlib.Path('/tmp/fresh'),))
 def test_rss(self):
  native=type('N',(),{'own_tree_rss':lambda self:(g.RSS+1,{})})()
  with patch.object(g.shutil,'disk_usage',return_value=type('D',(),{'free':g.FREE})()),patch.object(g.time,'monotonic',return_value=2):
   with self.assertRaises(ValueError):g.admission(1,(pathlib.Path('/tmp/fresh'),),native)
 def test_one_shot(self):
  p=plistlib.loads(g.plist('/python','/guard',[],pathlib.Path('/receipt')));self.assertIs(p['RunAtLoad'],True);self.assertIs(p['KeepAlive'],False);self.assertNotIn('StartInterval',p)
if __name__=='__main__':unittest.main()
class Lifecycle(unittest.TestCase):
 def runmock(self,fail=False):
  from contextlib import ExitStack
  from unittest.mock import Mock
  with tempfile.TemporaryDirectory() as d,ExitStack() as stack:
   d=pathlib.Path(d).resolve();view=d/'view';out=d/'science';receipt=d/'receipt';protocol=d/'protocol';bindingpath=d/'binding'
   native=Mock();native.descendants.return_value=[]
   executor=Mock();executor.NativeMac.return_value=native;executor.LIMITS={};executor.stop_requested=lambda *a:None
   executor.resource_preflight.return_value={'state':'PASS'};executor.run_phase.side_effect=([{'state':'STOP'}] if fail else [{'state':'COMPLETE'},{'state':'COMPLETE'}])
   binding={'launcher_sha256':g.PROTOCOL_SHA,'protocol_sha256':g.PROTOCOL_SHA,'view':str(view),'outdir':str(out),'receipt_dir':str(receipt),'science_protocol_sha256':g.SCIENCE_SHA}
   for name,value in [('ENTRY',1),('LEDGER_ROOT',d/'ledger')]:stack.enter_context(patch.object(g,name,value))
   for name,value in [('sha',g.PROTOCOL_SHA),('read',None),('admission',2),('pins',None),('load',executor),('verify',{'calibration_status':'INCONCLUSIVE','control_status':'INCONCLUSIVE'})]:
    m=stack.enter_context(patch.object(g,name,return_value=value))
    if name=='read':m.side_effect=lambda p:binding if p==bindingpath else {'pins':{}}
   for name in ('signal','setitimer'):stack.enter_context(patch.object(g.signal,name))
   stack.enter_context(patch.object(g.sys,'argv',['guardian','--view',str(view),'--protocol',str(protocol),'--binding',str(bindingpath),'--binding-sha',g.PROTOCOL_SHA,'--outdir',str(out),'--receipt-dir',str(receipt)]))
   if fail:
    with self.assertRaises(SystemExit):g.main()
   else:g.main()
   terminal=json.loads((receipt/'terminal.json').read_text());return executor.run_phase.call_count,terminal
 def test_full_bank_after_inconclusive_no_science_mock(self):
  n,r=self.runmock();self.assertEqual(n,2);self.assertEqual(r['state'],'FULL_DESCRIPTIVE_COMPLETE_NEEDS_INDEPENDENT_AUDIT');self.assertFalse(r['scientific_pass'])
 def test_failed_phase_no_retry(self):
  n,r=self.runmock(True);self.assertEqual(n,1);self.assertEqual(r['state'],'INCONCLUSIVE_EXECUTION_STOP_NO_RETRY')
