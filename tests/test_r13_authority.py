"""Private dispatch negative fixtures; no child spawn, model imports or signals."""
import unittest,tempfile,types,os,hashlib,time,sys
from pathlib import Path
from unittest.mock import patch
source_root=Path(__file__).resolve().parents[1]/'shock-radar/src'
sys.path.insert(0,str(source_root if source_root.exists() else Path(__file__).parent));import r13_full_registry as r;import r13_registry_core as c
class Authority(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.out=self.root/'out';self.out.mkdir();self.lock=self.root/'lock';self.auth=self.out/'auth.json';self.token='private-test';self.args=types.SimpleNamespace(dispatch=self.auth,out=self.out,mode='run');self.owner={'pid':111,'nonce':'owner'};self.a={'parent_pid':111,'nonce':'owner','secret_SHA':hashlib.sha256(self.token.encode()).hexdigest(),'out':str(self.out.resolve()),'fingerprint':'f','source_SHA':c.sha(r.__file__),'expires_monotonic':time.monotonic()+10,'mode':'run'};c.atomic(self.lock,self.owner)
 def tearDown(self):self.tmp.cleanup()
 def invoke(self,a=None):
  c.atomic(self.auth,a or self.a)
  with patch.dict(os.environ,{'R13_SESSION_SECRET':self.token}),patch.object(r.os,'getppid',return_value=111),patch.object(r.os,'getpid',return_value=222),patch.object(r.os,'getpgrp',return_value=222):r.dispatch(self.args,{},'f',self.lock)
 def reject(self,key,value):
  a=dict(self.a);a[key]=value
  with self.assertRaises(ValueError):self.invoke(a)
 def test_valid_one_use(self):
  self.invoke();self.assertFalse(self.auth.exists());self.assertTrue(self.auth.with_suffix('.consumed').exists())
  with self.assertRaises(FileExistsError):self.invoke()
 def test_wrong_parent(self):self.reject('parent_pid',333)
 def test_wrong_nonce(self):self.reject('nonce','other')
 def test_wrong_secret(self):self.reject('secret_SHA','bad')
 def test_wrong_out(self):self.reject('out',str(self.root/'other'))
 def test_wrong_fp(self):self.reject('fingerprint','other')
 def test_wrong_source(self):self.reject('source_SHA','bad')
 def test_expired(self):self.reject('expires_monotonic',0)
 def test_mode_substitution(self):self.reject('mode','recover')
 def test_nonisolated_pg(self):
  c.atomic(self.auth,self.a)
  with patch.dict(os.environ,{'R13_SESSION_SECRET':self.token}),patch.object(r.os,'getppid',return_value=111),patch.object(r.os,'getpid',return_value=222),patch.object(r.os,'getpgrp',return_value=111),self.assertRaises(ValueError):r.dispatch(self.args,{},'f',self.lock)
 def test_lock_foreign_parent(self):
  c.atomic(self.lock,{'pid':999,'nonce':'owner'})
  with self.assertRaises(ValueError):self.invoke()
 def test_secret_not_consumed_into_output(self):self.invoke();self.assertNotIn(self.token,self.auth.with_suffix('.consumed').read_text())
if __name__=='__main__':unittest.main()
