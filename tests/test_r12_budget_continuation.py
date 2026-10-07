from pathlib import Path
import unittest,tempfile,json,copy,datetime,sys,importlib.util
HERE=Path(__file__).resolve().parent;SOURCE=HERE if (HERE/'r12_budget_continuation.py').exists() else HERE.parent/'shock-radar/src'
spec=importlib.util.spec_from_file_location('r12',SOURCE/'r12_budget_continuation.py');r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
class Tests(unittest.TestCase):
 def spec(self):return {'deadline_UTC':'2026-10-09T09:00:00Z','cumulative_wall_seconds_cap':108000}
 def test_counters_must_be_conserved(self):
  r.verify_counters({'chronos_calls':64,'prophet_fits':690},{'chronos_calls':128,'prophet_fits':1380})
  with self.assertRaisesRegex(ValueError,'decreased'):r.verify_counters({'chronos_calls':64},{'chronos_calls':63})
 def test_absolute_deadline_refuses(self):
  with self.assertRaisesRegex(ValueError,'deadline'):r.guarded_total(self.spec(),362,datetime.datetime(2026,10,9,9,tzinfo=datetime.timezone.utc))
 def test_total_budget_exhaustion_refuses(self):
  with self.assertRaisesRegex(ValueError,'exhausted'):r.guarded_total(self.spec(),108000,datetime.datetime(2026,10,8,tzinfo=datetime.timezone.utc))
 def test_deadline_can_only_shorten_total(self):
  self.assertEqual(r.guarded_total(self.spec(),362,datetime.datetime(2026,10,9,8,59,tzinfo=datetime.timezone.utc)),422)
 def test_nominal_cap(self):self.assertEqual(r.guarded_total(self.spec(),362,datetime.datetime(2026,10,7,tzinfo=datetime.timezone.utc)),108000)
 def test_closed_checkpoint_receipt_and_immutability(self):
  with tempfile.TemporaryDirectory() as tmp:
   out=Path(tmp);(out/'checkpoints').mkdir();p=out/'checkpoints/a.json';r.atomic(p,{'status':'complete','chronos':{'x':1}});before=r.checkpoint_receipt(out);r.verify_preserved(out,before);r.atomic(p,{'status':'complete','chronos':{'x':2}})
   with self.assertRaisesRegex(ValueError,'changed'):r.verify_preserved(out,before)
 def test_uncertain_checkpoint_blocks(self):
  with tempfile.TemporaryDirectory() as tmp:
   out=Path(tmp);(out/'checkpoints').mkdir();r.atomic(out/'checkpoints/a.json',{'status':'complete','uncertain_inflight':'chronos'})
   with self.assertRaisesRegex(ValueError,'uncertain'):r.checkpoint_receipt(out)
 def test_open_checkpoint_blocks(self):
  with tempfile.TemporaryDirectory() as tmp:
   out=Path(tmp);(out/'checkpoints').mkdir();r.atomic(out/'checkpoints/a.json',{'status':'pending'})
   with self.assertRaisesRegex(ValueError,'open checkpoint'):r.checkpoint_receipt(out)
 def test_guard_changes_only_total_in_copy_preserves_original(self):
  with tempfile.TemporaryDirectory() as tmp:
   out=Path(tmp);r.atomic(out/'resource-ledger.json',{'cumulative_wall_s':362});seen=[]
   class Module:
    def start_guard(self,*args):seen.append(args);return 'finish'
   module=Module();full={'prospective_resources':{'wall_total_seconds_cap_proposal':21600,'rss_limit_bytes':2147483648,'per_invocation_wall_s_cap_proposal':600},'mask':['same'],'seed':20260927};before=copy.deepcopy(full)
   r.instrument(module,self.spec(),out);self.assertEqual(module.start_guard(out,full,{},[None],1),'finish');self.assertEqual(full,before);changed=seen[0][1];changed['prospective_resources']['wall_total_seconds_cap_proposal']=21600;self.assertEqual(changed,before)
class ConservationTests(unittest.TestCase):
 def fixture(self,tmp):
  out=Path(tmp)/'actual';out.mkdir();(out/'checkpoints').mkdir();receipts=Path(tmp)/'actual-continuation';receipts.mkdir();r.atomic(out/'checkpoints/a.json',{'status':'complete'});counters={'chronos_calls':64};r.atomic(out/'counters.json',counters);r.atomic(out/'resource-ledger.json',{'cumulative_wall_s':362.})
  spec={'initial_complete_checkpoint_SHAs':r.checkpoint_receipt(out),'measured_first_chunk':{'counters':counters,'cumulative_wall_s':362.}}
  return out,receipts,spec
 def close(self,out,receipts):
  latest={'count':1,'checkpoints':r.checkpoint_receipt(out),'counters':r.read(out/'counters.json'),'wall':r.read(out/'resource-ledger.json')['cumulative_wall_s']};r.atomic(receipts/'invocation-0001.json',{'status':'CLOSED','count':1});r.atomic(receipts/'latest-closed.json',latest);r.atomic(receipts/'driver-state.json',{'status':'CLOSED','count':1,'latest_closed_SHA':r.sha(receipts/'latest-closed.json')})
 def test_check_refuses_exhausted_cumulative_count(self):
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as tmp:
   out,receipts,spec=self.fixture(tmp);r.atomic(out/'invocation-result.json',{'status':'INCONCLUSIVE_PARTIAL_RESUMABLE'})
   argv=['r12','--amendment',str(HERE/'BUDGET_AMENDMENT.json') if (HERE/'BUDGET_AMENDMENT.json').exists() else str(HERE.parent/'shock-radar/protocol/chronos2_resource_amendment_20261007.json'),'--receipt-dir',str(receipts),'--view',tmp,'--out',str(out),'--check']
   with patch.object(sys,'argv',argv),patch.object(r,'validate'),patch.object(r,'continuity',return_value={'count':197}),patch.object(r,'run_original') as model:
    with self.assertRaisesRegex(ValueError,'cap exhausted'):r.main()
    model.assert_not_called()
 def test_check_rejects_actual_output_lock_before_validation(self):
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as tmp:
   out,receipts,spec=self.fixture(tmp);_,_,lock=r.canonical_paths(out,receipts);r.atomic(lock,{'pid':1})
   argv=['r12','--amendment',str(HERE/'BUDGET_AMENDMENT.json') if (HERE/'BUDGET_AMENDMENT.json').exists() else str(HERE.parent/'shock-radar/protocol/chronos2_resource_amendment_20261007.json'),'--receipt-dir',str(receipts),'--view',tmp,'--out',str(out),'--check']
   with patch.object(sys,'argv',argv),patch.object(r,'validate') as validate,patch.object(r,'run_original') as model:
    with self.assertRaisesRegex(ValueError,'locked'):r.main()
    validate.assert_not_called();model.assert_not_called()
 def test_check_rejects_started_transaction_without_dispatch(self):
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as tmp:
   out,receipts,spec=self.fixture(tmp);r.atomic(receipts/'driver-state.json',{'status':'STARTED','count':1})
   argv=['r12','--amendment',str(HERE/'BUDGET_AMENDMENT.json') if (HERE/'BUDGET_AMENDMENT.json').exists() else str(HERE.parent/'shock-radar/protocol/chronos2_resource_amendment_20261007.json'),'--receipt-dir',str(receipts),'--view',tmp,'--out',str(out),'--check']
   with patch.object(sys,'argv',argv),patch.object(r,'validate'),patch.object(r,'run_original') as model:
    with self.assertRaisesRegex(ValueError,'STARTED'):r.main()
    model.assert_not_called()
 def test_receipt_alias_cannot_bypass_output_lock(self):
  with tempfile.TemporaryDirectory() as tmp:
   out,receipts,spec=self.fixture(tmp);a=r.canonical_paths(out,receipts);b=r.canonical_paths(out/'..'/'actual',receipts);self.assertEqual(a,b)
   with self.assertRaisesRegex(ValueError,'noncanonical'):r.canonical_paths(out,Path(tmp)/'elsewhere')
 def test_count_cap_survives_restart(self):
  with tempfile.TemporaryDirectory() as tmp:
   out,receipts,spec=self.fixture(tmp);self.close(out,receipts);previous=r.continuity(spec,out,receipts)
   with self.assertRaisesRegex(ValueError,'cumulative invocation'):r.reserve(receipts,previous,1)
 def test_started_transaction_blocks_restart(self):
  with tempfile.TemporaryDirectory() as tmp:
   out,receipts,spec=self.fixture(tmp);p=r.continuity(spec,out,receipts);r.reserve(receipts,p,197)
   with self.assertRaisesRegex(ValueError,'STARTED'):r.continuity(spec,out,receipts)
 def test_latest_checkpoint_loss_blocks_replay(self):
  with tempfile.TemporaryDirectory() as tmp:
   out,receipts,spec=self.fixture(tmp);r.atomic(out/'checkpoints/b.json',{'status':'complete'});self.close(out,receipts);r.continuity(spec,out,receipts);(out/'checkpoints/b.json').unlink()
   with self.assertRaisesRegex(ValueError,'set changed'):r.continuity(spec,out,receipts)
 def test_counter_rollback_to_initial_blocks(self):
  with tempfile.TemporaryDirectory() as tmp:
   out,receipts,spec=self.fixture(tmp);r.atomic(out/'counters.json',{'chronos_calls':128});self.close(out,receipts);r.atomic(out/'counters.json',{'chronos_calls':64})
   with self.assertRaisesRegex(ValueError,'rolled back'):r.continuity(spec,out,receipts)
 def test_wall_rollback_to_initial_blocks(self):
  with tempfile.TemporaryDirectory() as tmp:
   out,receipts,spec=self.fixture(tmp);r.atomic(out/'resource-ledger.json',{'cumulative_wall_s':724.});self.close(out,receipts);r.atomic(out/'resource-ledger.json',{'cumulative_wall_s':362.})
   with self.assertRaisesRegex(ValueError,'rolled back'):r.continuity(spec,out,receipts)
 def test_history_loss_blocks(self):
  with tempfile.TemporaryDirectory() as tmp:
   out,receipts,spec=self.fixture(tmp);self.close(out,receipts);(receipts/'invocation-0001.json').unlink()
   with self.assertRaisesRegex(ValueError,'history lost'):r.continuity(spec,out,receipts)
 def test_external_dispatch_rejected_before_original_import(self):
  import subprocess
  process=subprocess.run([sys.executable,str(SOURCE/'r12_budget_continuation.py'),'--amendment','absent','--receipt-dir','absent','--view','absent','--out','absent','--one-child'],capture_output=True,text=True)
  self.assertNotEqual(process.returncode,0);self.assertIn('external child dispatch prohibited',process.stderr)
 def test_scoped_token_one_use_and_parent_bound(self):
  import os,time
  with tempfile.TemporaryDirectory() as tmp:
   out,receipts,spec=self.fixture(tmp);lock=Path(tmp)/'lock';r.atomic(lock,{'pid':os.getppid(),'nonce':'n'});r.atomic(receipts/'driver-state.json',{'status':'STARTED','count':1});token=receipts/'token.json';args=['--mode','run'];auth={'parent_pid':os.getppid(),'out':str(out),'receipts':str(receipts),'view':str(Path(tmp).resolve()),'args_SHA':r.hashlib.sha256(json.dumps(args).encode()).hexdigest(),'driver_SHA':r.sha(r.__file__),'nonce':'n','count':1,'expires_monotonic':time.monotonic()+45};r.atomic(token,auth);token.chmod(0o600);r.dispatch_auth(token,out,receipts,Path(tmp),args,lock)
   with self.assertRaisesRegex(ValueError,'authorization'):r.dispatch_auth(token,out,receipts,Path(tmp),args,lock)
   auth['parent_pid']=-1;r.atomic(token,auth);token.chmod(0o600)
   with self.assertRaisesRegex(ValueError,'external child'):r.dispatch_auth(token,out,receipts,Path(tmp),args,lock)
if __name__=='__main__':unittest.main()
