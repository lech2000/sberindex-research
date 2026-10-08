import pathlib,importlib.util,tempfile,json,datetime,os,socket,hashlib,types,unittest
from unittest.mock import patch
FILE=pathlib.Path(__file__).parents[1]/'economic-atlas/src/atlas_m4_durable.py'
s=importlib.util.spec_from_file_location('outer_budget_fixture',FILE);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class ControllerBudget(unittest.TestCase):
 def fixture(self,out):
  out=out.resolve()
  control=out/'runtime';control.mkdir();ledger=out/'ledger';ledger.mkdir();utc=datetime.datetime(2026,10,8,2,tzinfo=datetime.timezone.utc)
  (out/'controller.py').write_text('fixture only')
  proof={'state':'AUTHORITATIVE_M1_OWNED_PARENTS_GONE','checked_at_UTC':utc.isoformat(),'signals':0,'known_pids':{str(pid):{'ps_exit':1,'stdout':'','stderr':''} for pid in [72250,72253]}};(control/'ROOT_M1_GONE.json').write_text(json.dumps(proof));qp=m.sha(control/'ROOT_M1_GONE.json')
  entry={'origin':m.CONTROLLER_ORIGIN,'uid':os.getuid(),'host':socket.gethostname(),'monotonic_entry':100.,'utc_entry':utc.isoformat(),'quiescence_sha256':qp,'controller_source_sha256':m.sha(out/'controller.py')};(control/'entry.json').write_text(json.dumps(entry));binding={'controller_monotonic_entry':100.,'controller_entry_sha256':m.sha(control/'entry.json'),'controller_utc_entry':utc.isoformat(),'quiescence_sha256':qp,'controller_source_sha256':m.sha(out/'controller.py')};(control/'ROOT_BINDING.json').write_text('{}');lease=ledger/(str(os.getuid())+'-M4-bootstrap-'+hashlib.sha256(m.KEY.encode()).hexdigest()+'.json');binding['bootstrap_reservation']=str(lease)
  data={'controller_entry_sha256':binding['controller_entry_sha256'],'one_use_key':m.KEY,'binding_sha256':m.sha(control/'ROOT_BINDING.json'),'outdir':'/private/tmp/atlas-m4-fullbank-actual-20261008-v1/science','receipt_dir':'/private/tmp/atlas-m4-fullbank-actual-20261008-v1/receipts'};lease.write_text(json.dumps(data));return control,ledger,binding,utc,data
 def anchor(self,b,control,ledger,utc,mono=110):
  with patch.object(m,'CONTROLLER_ROOT',control),patch.object(m,'LEDGER_ROOT',ledger):return m.controller_anchor(b,mono,utc+datetime.timedelta(seconds=10))
 def test_samehost_original_anchor_conserved(self):
  with tempfile.TemporaryDirectory() as d:
   c,l,b,u,_=self.fixture(pathlib.Path(d));self.assertEqual(self.anchor(b,c,l,u),100)
 def test_finite_bool_future_old_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   c,l,b,u,_=self.fixture(pathlib.Path(d))
   for v in [True,float('nan'),float('inf'),111,-11,'100',None]:
    with self.subTest(v=v),self.assertRaises(ValueError):self.anchor(dict(b,controller_monotonic_entry=v),c,l,u)
 def test_origin_uid_host_mismatch_rejected(self):
  for field,value in [('origin','RESET'),('uid',True),('uid',-1),('host','foreign')]:
   with tempfile.TemporaryDirectory() as d:
    c,l,b,u,_=self.fixture(pathlib.Path(d));e=json.loads((c/'entry.json').read_text());e[field]=value;(c/'entry.json').write_text(json.dumps(e));b['controller_entry_sha256']=m.sha(c/'entry.json')
    with self.assertRaises(ValueError):self.anchor(b,c,l,u)
 def test_utc_monotonic_skew_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   c,l,b,u,_=self.fixture(pathlib.Path(d))
   with self.assertRaises(ValueError):self.anchor(b,c,l,u+datetime.timedelta(seconds=20))
 def test_anchor_capsule_reset_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   c,l,b,u,_=self.fixture(pathlib.Path(d));b['controller_monotonic_entry']=105
   with self.assertRaises(ValueError):self.anchor(b,c,l,u)
 def test_handoff_binding_namespace_mismatch_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   c,l,b,u,data=self.fixture(pathlib.Path(d));data['outdir']='/private/tmp/alternate';pathlib.Path(b['bootstrap_reservation']).write_text(json.dumps(data))
   with self.assertRaises(ValueError):self.anchor(b,c,l,u)
 def test_existing_live_m1_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   c,l,b,u,_=self.fixture(pathlib.Path(d));q=json.loads((c/'ROOT_M1_GONE.json').read_text());q['known_pids']['72253']['ps_exit']=0;(c/'ROOT_M1_GONE.json').write_text(json.dumps(q));b['quiescence_sha256']=m.sha(c/'ROOT_M1_GONE.json');e=json.loads((c/'entry.json').read_text());e['quiescence_sha256']=b['quiescence_sha256'];(c/'entry.json').write_text(json.dumps(e));b['controller_entry_sha256']=m.sha(c/'entry.json')
   with self.assertRaises(ValueError):self.anchor(b,c,l,u)
 def test_admission_subtracts_controller_elapsed(self):
  now=datetime.datetime(2026,10,8,2,tzinfo=datetime.timezone.utc);self.assertEqual(m.admission(now,startup=100),int(m.TOTAL_SECONDS-m.HISTORICAL_SECONDS-100-m.FINALIZATION_SECONDS))
 def test_controller_outputs_included_once(self):
  with tempfile.TemporaryDirectory() as d:
   root=pathlib.Path(d);science=root/'science';science.mkdir();receipts=root/'receipts';receipts.mkdir();control=root/'runtime';control.mkdir();ledger=root/'ledger';ledger.mkdir();lease=ledger/'model.json'
   for path,data in [(science/'rows',b'123'),(receipts/'receipt',b'1234'),(control/'binding',b'12345'),(lease,b'12')]:path.write_bytes(data)
   with patch.object(m,'CONTROLLER_ROOT',control),patch.object(m,'LEDGER_ROOT',ledger):self.assertEqual(m.combined_output(science,receipts,lease),(14,11))
 def test_whole_output_cap_stops_before_probe(self):
  with patch.object(m.time,'monotonic',return_value=10),patch.object(m,'utcnow',return_value=datetime.datetime(2026,10,8,2,tzinfo=datetime.timezone.utc)),patch.object(m,'combined_output',return_value=(268435457,1)):
   with self.assertRaises(InterruptedError):m.whole_guard(0,pathlib.Path('/private/tmp/science'),pathlib.Path('/private/tmp/receipt'),pathlib.Path('/private/tmp/lease'))
 def test_whole_controller_time_stops_at_original_budget(self):
  with patch.object(m.time,'monotonic',return_value=m.TOTAL_SECONDS),patch.object(m,'utcnow',return_value=datetime.datetime(2026,10,8,2,tzinfo=datetime.timezone.utc)):
   with self.assertRaises(InterruptedError):m.whole_guard(0,pathlib.Path('/private/tmp/science'),pathlib.Path('/private/tmp/receipt'),pathlib.Path('/private/tmp/lease'))
 def test_plist_remains_once_without_restart(self):
  import plistlib
  job=plistlib.loads(m.plist('python','launcher','repo','cal','bind','SHA','receipt','science'));self.assertTrue(job['RunAtLoad']);self.assertFalse(job['KeepAlive']);self.assertNotIn('StartInterval',job);self.assertNotIn('StartCalendarInterval',job)
if __name__=='__main__':unittest.main()
