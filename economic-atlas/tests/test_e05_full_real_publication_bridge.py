"""Hermetic lifecycle and real temporary-directory publisher checks, no science."""
import ast,hashlib,json,pathlib,sys,tempfile,unittest
from types import SimpleNamespace
from unittest.mock import patch,Mock
sys.path.insert(0,str(pathlib.Path(__file__).parents[1]/'src'))
import e05_full_real_publication_bridge as b
import e05_full_execution_controller as c
P=pathlib.Path
class Test(unittest.TestCase):
 def temp(self):return tempfile.TemporaryDirectory(dir='/private/tmp')
 def test_same_frozen_algorithm_ast(self):
  old=ast.parse(P(b.frozen.__file__).read_text());new=ast.parse(P(b.__file__).read_text())
  x=next(n for n in old.body if isinstance(n,ast.FunctionDef)and n.name=='finalize_mockable')
  y=next(n for n in new.body if isinstance(n,ast.FunctionDef)and n.name=='_qualified_finalize')
  self.assertEqual(ast.dump(ast.Module(body=x.body[3:],type_ignores=[])),ast.dump(ast.Module(body=y.body,type_ignores=[])))
 def test_real_publisher_no_overwrite(self):
  with self.temp() as d:
   root=P(d);stage=root/'stage';stage.mkdir();(stage/'value').write_bytes(b'owned');target=root/'target';target.mkdir();(target/'foreign').write_bytes(b'keep')
   with self.assertRaises(FileExistsError):b.atomic_publish_no_replace(stage,target)
   self.assertEqual((target/'foreign').read_bytes(),b'keep');self.assertTrue(stage.exists())
 def test_real_publisher_atomic_directory(self):
  with self.temp() as d:
   root=P(d);stage=root/'stage';stage.mkdir();(stage/'value').write_bytes(b'owned');target=root/'target'
   b.atomic_publish_no_replace(stage,target);self.assertFalse(stage.exists());self.assertEqual((target/'value').read_bytes(),b'owned')
 def test_publisher_no_fallback_for_unknown_platform(self):
  with self.temp()as d,patch.object(b.sys,'platform','unavailable'):
   root=P(d);stage=root/'stage';stage.mkdir()
   with self.assertRaises(RuntimeError):b.atomic_publish_no_replace(stage,root/'target')
   self.assertTrue(stage.exists())
 def test_publisher_needs_siblings(self):
  with self.temp()as d:
   root=P(d);stage=root/'stage';stage.mkdir();folder=root/'other';folder.mkdir()
   with self.assertRaises(ValueError):b.atomic_publish_no_replace(stage,folder/'target')
 def test_path_refuses_symlink_parents(self):
  with self.temp()as d:
   root=P(d);folder=root/'dir';folder.mkdir();(root/'link').symlink_to(folder)
   with self.assertRaises(ValueError):b.canonical_path(root/'link'/'missing',exists=False)
 def view(self,d):
  root=P(d);raw=root/'raw';journals=root/'journal';raw.mkdir();journals.mkdir();territory=root/'tids.json';territory.write_text('[1,2]');(raw/'bytes').write_bytes(b'a'*70000)
  key='cell/0';(journals/(hashlib.sha256(key.encode()).hexdigest()+'.STARTED.json')).write_text('{}')
  return b.SourceView(raw,journals,territory,lambda:None)
 def test_composite_inventory_stream_bounds(self):
  with self.temp()as d:
   view=self.view(d);self.assertEqual(len(view.inventory),3);chunks=list(view.read_chunks('bytes'));self.assertEqual(list(map(len,chunks)),[65536,4464]);self.assertEqual(b''.join(chunks),b'a'*70000)
 def test_source_inode_rebound_refuses_same_bytes(self):
  with self.temp()as d:
   view=self.view(d);p=view.raw/'bytes';p.rename(view.raw/'old');p.write_bytes(b'a'*70000)
   with self.assertRaises(ValueError):list(view.read_chunks('bytes'))
 def test_source_same_inode_mutation_refuses(self):
  with self.temp()as d:
   view=self.view(d);(view.raw/'bytes').write_bytes(b'b'*70000)
   with self.assertRaises(ValueError):list(view.read_chunks('bytes'))
 def test_late_journal_or_raw_not_omitted(self):
  for kind in ('journal','raw'):
   with self.temp()as d:
    view=self.view(d)
    (view.journals/'late.STARTED.json' if kind=='journal'else view.raw/'late').write_bytes(b'partial')
    with self.assertRaisesRegex(ValueError,'path set'):view.verify_namespace(full=True)
 def test_directory_rebound_detected(self):
  with self.temp()as d:
   view=self.view(d);view.journals.rename(P(d)/'old-journals');view.journals.mkdir()
   with self.assertRaisesRegex(ValueError,'directory rebound'):view.verify_namespace()
 def test_final_namespace_stat_matches_original(self):
  with self.temp()as d:
   view=self.view(d);view.verify_namespace(full=True)
   (view.raw/'bytes').write_bytes(b'changed')
   with self.assertRaisesRegex(ValueError,'source stat'):view.verify_namespace(full=True)
 def test_inventory_symlink_refuses(self):
  with self.temp()as d:
   view=self.view(d);(view.raw/'link').symlink_to(view.territory)
   with self.assertRaises(ValueError):b.SourceView(view.raw,view.journals,view.territory,lambda:None)
 def test_composite_inventory_collision(self):
  with self.temp()as d:
   view=self.view(d);(view.raw/'territory-universe.json').write_text('[1,2]')
   with self.assertRaises(ValueError):b.SourceView(view.raw,view.journals,view.territory,lambda:None)
 def test_journal_extra_not_silently_accepted(self):
  with self.temp()as d:
   view=self.view(d);(view.journals/'unexpected.json').write_text('{}')
   with self.assertRaises(ValueError):b.SourceView(view.raw,view.journals,view.territory,lambda:None)
 def test_no_raw_created_before_engine_keeps_empty_view(self):
  with self.temp()as d:
   root=P(d);journals=root/'journals';journals.mkdir();territory=root/'tids';territory.write_text('[1,2]')
   view=b.SourceView(root/'raw',journals,territory,lambda:None)
   self.assertEqual(set(view.inventory),{'territory-universe.json'});self.assertFalse((root/'raw').exists())
   (root/'raw').mkdir()
   with self.assertRaisesRegex(ValueError,'appeared'):list(view.read_chunks('territory-universe.json'))
 def test_audit_manifest_not_rebound(self):
  import e05_full_numeric_adapter as n
  repo=P(b.__file__).resolve().parents[2]
  with self.temp()as d:
   root=P(d);target=root/'publication';target.mkdir();manifest=target/'publication-manifest.json';manifest.write_text('{}');initial=b.v.sha(manifest)
   (root/'raw').mkdir();(root/'journals').mkdir();(root/'territory').write_text('[1,2,3]')
   def guard():pass
   guard.roots=[root];guard.anchor=0
   admission={'source_pins':{name:b.v.sha(repo/name)for name in ['economic-atlas/src/e05_full_real_publication_bridge.py','economic-atlas/src/e05_full_publication_finalizer_v5.py','economic-atlas/src/e05_full_publication_validator_v5.py','economic-atlas/src/e05_full_numeric_adapter.py']},'source_binding':{},'real_IO_resource_report_SHA':'a'*64,'spec':dict(whole_seconds=999999999,audit_receipt_reserve_seconds=30,RSS_bytes=1024**3,output_bytes=128*1024**2,minimum_free_bytes=1024**3,CPU_threads=1)}
   def change(_):manifest.write_text('{"changed":true}');return {}
   adapter=Mock();adapter.audit.return_value={'publication_manifest_SHA':initial}
   with patch.object(b,'validate_original_admission',return_value={'remaining_quality_control_cost_state':'INDEPENDENTLY_ADMITTED'}),patch.object(b,'_qualified_finalize',return_value={}),patch.object(n,'Admission'),patch.object(n,'Adapter',return_value=adapter),patch.object(c,'validate_resource_report',side_effect=change):
    with self.assertRaisesRegex(ValueError,'SHA'):
     b.complete_and_audit(repo=repo,raw_root=root/'raw',publication_root=target,stage_root=root/'stage',journal_root=root/'journals',territory_file=root/'territory',guard=guard,original_operation={},admission=admission,finalization_lease=root/'lease')
   self.assertFalse(P(str(root/'lease')+'.METRIC_AUDIT').exists())
 def bindings(self):
  source=c.SOURCE_BINDING
  spec={'whole_seconds':3600,'finalization_reserve_seconds':600}
  admission=dict(spec=spec,source_binding=source,independent_source_ACK_SHA='b'*64,real_IO_resource_report_SHA='a'*64)
  operation=dict(operation=b.OPERATION_KEY,state='STARTED',original_anchor=100,whole_seconds=3600,finalization_reserve_seconds=600,source_binding=source,admissionreportSHA='a'*64,territory_ids_SHA='c'*64)
  class Guard:
   anchor=100;whole_seconds=3600;finalization_reserve_seconds=600;source_binding=source;resource_admission_SHA='a'*64;qualified_e05_audit_io=True;phase='publication'
   def __call__(self):pass
  return admission,operation,Guard()
 def test_actual_report_revalidated_not_boolean(self):
  a,o,g=self.bindings()
  with patch.object(c,'validate_resource_report',side_effect=ValueError('actual proof absent'))as check:
   with self.assertRaisesRegex(ValueError,'actual proof'):b.validate_original_admission(a,o,g)
   check.assert_called_once_with(a)
 def test_same_original_report_binding_required(self):
  a,o,g=self.bindings();o['admissionreportSHA']='d'*64
  with patch.object(c,'validate_resource_report',return_value={}):
   with self.assertRaisesRegex(ValueError,'report SHA'):b.validate_original_admission(a,o,g)
 def test_original_clock_cannot_reset(self):
  a,o,g=self.bindings();g.anchor=101
  with patch.object(c,'validate_resource_report',return_value={}):
   with self.assertRaisesRegex(ValueError,'clock'):b.validate_original_admission(a,o,g)
 def test_original_guard_still_science_refuses(self):
  a,o,g=self.bindings();g.phase='science'
  with patch.object(c,'validate_resource_report',return_value={}):
   with self.assertRaisesRegex(ValueError,'post-reap'):b.validate_original_admission(a,o,g)
 def test_original_reserve_no_replacement(self):
  a,o,g=self.bindings();a['spec']['finalization_reserve_seconds']=700
  with patch.object(c,'validate_resource_report',return_value={}):
   with self.assertRaisesRegex(ValueError,'reserve'):b.validate_original_admission(a,o,g)
 def test_fresh_interface_refuses_standalone(self):
  with self.assertRaises(RuntimeError):b.execute()
 def test_real_callbacks_not_mock_tagged(self):
  self.assertFalse(hasattr(b.atomic_publish_no_replace,'source_only_mock'));self.assertFalse(hasattr(b.SourceView.read_chunks,'source_only_mock'))
if __name__=='__main__':unittest.main()
