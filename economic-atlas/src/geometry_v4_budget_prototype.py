"""Pure admission prototype only. Not an executor, native probe or launch authority.
One foreground launch, no resume; caller must provide independently verified
own-tree RSS/free/output snapshots and original native preflight. Sampled checks
cannot establish continuous caps or measure their own final receipt IO.
"""
import math
WALL_SECONDS=4200.;RSS_BYTES=1073741824;FREE_BYTES=1073741824;OUTPUT_BYTES=268435456
STAGES=('startup_probe','full_real','full_controls_210','finalization')
class BudgetStop(RuntimeError): pass
class ConservedBudget:
 def __init__(self, clock, startup_charge=0.):
  if isinstance(startup_charge,bool) or not isinstance(startup_charge,(float,int)) or not math.isfinite(startup_charge) or startup_charge<0:raise ValueError('invalid startup charge')
  self.clock=clock;self.origin=clock();self.startup_charge=startup_charge
  if isinstance(self.origin,bool) or not isinstance(self.origin,(int,float)) or not math.isfinite(self.origin):raise ValueError("invalid original clock")
  self.last=self.origin;self.stage_index=0;self.stopped=False
 def check(self, stage, *, own_tree_rss, free_bytes, output_bytes, threads, native_preflight_pass):
  if self.stopped:raise BudgetStop('STOP terminal; no restart/resume')
  now=self.clock();elapsed=self.startup_charge+(now-self.origin)
  try:
   if stage not in STAGES or STAGES.index(stage)<self.stage_index:raise BudgetStop('stage regression')
   if not math.isfinite(now) or now<self.last or elapsed>=WALL_SECONDS:raise BudgetStop('conserved wall exhausted or invalid clock')
   for v in (own_tree_rss,free_bytes,output_bytes):
    if isinstance(v,bool) or not isinstance(v,int) or v<0:raise BudgetStop('missing native/resource measurement')
   if threads!=1 or isinstance(threads,bool) or native_preflight_pass is not True:raise BudgetStop('CPU1/valid own-child preflight required')
   if own_tree_rss>RSS_BYTES or free_bytes<FREE_BYTES or output_bytes>OUTPUT_BYTES:raise BudgetStop('resource cap')
  except BudgetStop:
   self.stopped=True;raise
  self.last=now;self.stage_index=STAGES.index(stage)
  return {'elapsed_seconds':elapsed,'remaining_seconds':WALL_SECONDS-elapsed,'stage':stage,'continuous_resource_pass':False,'execution_authorized':False}
