"""Single parent-authorized original E05 full worker. Never standalone/retry."""
import time
ENTRY=time.monotonic()
import argparse,hashlib,json,os,pathlib,signal,sys
P=pathlib.Path
def main(argv=None):
 import e05_full_execution_controller as c
 ap=argparse.ArgumentParser();ap.add_argument('--repo',type=P,required=True);ap.add_argument('--root-binding',type=P,required=True);args=ap.parse_args(argv)
 # No NumPy/pandas/science import until exact single-use parent authorization.
 secret=os.environ.get('E05_PRIVATE_TOKEN','')
 if not secret:raise RuntimeError('external worker dispatch refused')
 auth_path=c.CONTROL/'worker-authorization.json';deadline=ENTRY+10
 while not auth_path.exists():
  if time.monotonic()>=deadline:raise RuntimeError('bounded parent authorization absent')
  time.sleep(.01)
 auth=c.read(c.regular(auth_path));bound={'path':str(args.root_binding),'SHA':auth['root_binding_SHA'],'stat':auth['root_binding_stat']};c.check_snapshot(bound);binding=c.read(c.regular(args.root_binding));spec=c.validate(binding,args.repo);c.check_snapshot(bound)
 if auth['parent_PID']!=os.getppid()or auth['owned_PID']!=os.getpid()or auth['UID']!=os.getuid()or auth['repo']!=str(args.repo)or auth['root_binding_SHA']!=c.sha(args.root_binding)or auth['source_pins']!=binding['source_pins']or auth['python_SHA']!=binding['python_SHA']or auth['secret_SHA']!=hashlib.sha256(secret.encode()).hexdigest()or (auth['out'],auth['control'],auth['ledger'])!=(str(c.OUT),str(c.CONTROL),str(c.LEDGER))or auth['whole_seconds']!=spec['whole_seconds']:raise RuntimeError('parent/child/source/token/out scope mismatch')
 if os.getpgrp()!=os.getpid()or os.getsid(0)!=os.getpid():raise RuntimeError('owned isolated session required')
 anchor=c.finite(auth['anchor'])
 if anchor>ENTRY or time.monotonic()-anchor>=spec['whole_seconds']-spec['finalization_reserve_seconds']:raise RuntimeError('original clock exhausted/future')
 c.check_snapshot(bound);c.once(c.CONTROL/'worker-consumed.json',dict(worker_PID=os.getpid(),authorization_SHA=c.sha(auth_path),original_anchor=anchor))
 os.environ.pop('E05_PRIVATE_TOKEN',None)
 for name in c.THREADS:
  if os.environ.get(name)!='1':raise RuntimeError('inherited CPU1 required')
 for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,c.stop)
 sys.path.insert(0,str(args.repo/'economic-atlas/src'))
 native=c.load(args.repo,'atlas_m1_executor.py').NativeMac();guard=c.Guard(spec,anchor,[c.OUT,c.CONTROL,c.LEDGER],native,binding);guard.binding_snapshot=bound;guard()
 c.private_dir(c.OUT);c.private_dir(c.OUT/'journals')
 from e05_full_guardian_toolkit_v2 import Journal
 from e05_full_receipt_adapter_v5 import Adapter
 engine=c.load(args.repo,'atlas_e05_remaining_v2.py')
 import pandas as pd
 a6=engine._load(args.repo,'a6_temporal.py');panel=pd.read_parquet(args.repo/'economic-atlas/data/panel_v1.parquet');tids,months,_,_=a6.build_monthly_shares(panel)
 protocol=c.read(args.repo/c.PROTOCOL)
 tids=[int(v)for v in tids]
 if len(tids)!=1896 or len(set(tids))!=1896 or tids!=sorted(tids)or list(months)!=protocol['months']:raise ValueError('full original ordered native universe')
 guard();c.once(c.CONTROL/'territory-universe.json',tids)
 c.once(c.CONTROL/'territory-binding.json',dict(panel_SHA=c.PANEL_SHA,territory_file_SHA=c.sha(c.CONTROL/'territory-universe.json'),territory_ids_SHA=hashlib.sha256(json.dumps(tids,sort_keys=True,separators=(',',':')).encode()).hexdigest(),original_anchor=anchor,source_pins=binding['source_pins']))
 del panel
 journal=Journal(c.OUT/'journals',guard);adapter=Adapter(protocol,journal,guard,c.OUT/'raw')
 try:
  with adapter.observe(engine):result=engine.execute(args.repo,args.repo/c.PROTOCOL,c.OUT/'raw',guard,adapter.cell_callback)
  guard();c.once(c.CONTROL/'worker-result.json',result);return 0
 except BaseException as e:
  # No retry or new cell after stop; all STARTED/RESPONSE bytes retained.
  try:c.once(c.CONTROL/'worker-stop.json',dict(error=type(e).__name__+': '+str(e),original_anchor=anchor,automatic_retry=False,scientific_pass=False))
  finally:raise
if __name__=='__main__':sys.exit(main())
