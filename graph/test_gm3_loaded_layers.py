import unittest
from gm3_loaded_layers import period, exact8
class AdmissionTests(unittest.TestCase):
 def test_cumulative_periods(self):
  self.assertEqual(period(2024,'Январь-июнь'),'2024-01-01/2024-06-30')
  self.assertEqual(period(2024,'Январь-декабрь'),'2024-01-01/2024-12-31')
 def test_unknown_period_not_inferred(self):
  self.assertIsNone(period(2024,'Январь-май'))
 def test_code_exact_only(self):
  self.assertEqual(exact8('79-701-000-000'),'79701000')
  self.assertIsNone(exact8('79701000123'))
  self.assertIsNone(exact8('municipality name'))
  self.assertIsNone(exact8('7970100'))

class SyntheticEndToEndControls(unittest.TestCase):
 """Explicit synthetic fixtures: component controls only, not source evidence."""
 def test_quarantine_missing_zero_provenance_and_immutability(self):
  import tempfile,pathlib,json,sqlite3,pandas as pd
  from gm3_loaded_layers import run,sha,UPPER
  from gm3_snapshot import SCHEMA
  with tempfile.TemporaryDirectory() as tmp:
   r=pathlib.Path(tmp);base=r/'base.sqlite';c=sqlite3.connect(base);c.executescript(SCHEMA)
   c.execute("insert into dataset_release values('dict','fixture','fixture','fixture','fixture',null,null,null,'fixture')")
   c.execute("insert into municipality values(1,'fixture',1)")
   c.execute("insert into administrative_identity values('i',1,'OKTMO','79701000000',2020,2025,'dict','proposed','unknown')")
   c.commit();c.close();sources=[]
   def add(name,obj):
    p=r/(name+('.parquet' if isinstance(obj,pd.DataFrame) else '.json'))
    if isinstance(obj,pd.DataFrame):obj.to_parquet(p,index=False)
    else:p.write_text(json.dumps(obj))
    sources.append({'name':name,'path':str(p),'sha256':sha(p),'bytes':p.stat().st_size})
   sources.append({'name':'base_graph','path':str(base),'sha256':sha(base),'bytes':base.stat().st_size})
   meta=[];receipt=[]
   for code in ['Y48423005','Y48423007','Y48213002']:
    unit='Человек' if code=='Y48423005' else 'Рубль'
    common={'indicator_code':code,'indicator_name':'fixture concept '+code,'indicator_unit':unit,'oktmo':'79701000','region_id':'79','mun_level':UPPER,'okved2':'A','year':2024,'indicator_period':'Январь-декабрь','oktmo_history':'Без изменений','oktmo_year_from':'2020','oktmo_year_to':'2025','indicator_value':0.}
    rows=[common.copy(),dict(common,okved2='B',indicator_value=None),dict(common,okved2='C',indicator_value=1.),dict(common,okved2='C',indicator_value=2.),dict(common,okved2='D',indicator_unit='unknown'),dict(common,okved2='E',oktmo='unknown'),dict(common,okved2='F',indicator_period='Январь-май'),dict(common,okved2='G',oktmo_year_to='2024')]
    add(code,pd.DataFrame(rows));meta.append({'indicator_code':code})
    if code!='Y48213002':
     rows[0]['indicator_value']=1.;add(code+'_v20260928',pd.DataFrame(rows));receipt.append({'indicator':code})
   add('tochno_manifest',{'datasets':meta});add('v20260928_receipt',receipt);add('migration_reference',pd.DataFrame({'fixture_only':[True]}))
   add('migration_verified',pd.DataFrame([{'territory_id':1,'code':'79701000000','year':2023,'period':'год','age':'Всего','gender':'Женщины','value':-2.,'indicator_value':-2.,'code_globally_unique':True,'dictionary_time_core':True,'oktmo_history':'Без изменений','value_verified':True,'concept':'net_migration_total','unit':'person','_merge':'both'}]))
   add('mobility_native_mapping',pd.DataFrame([{'native_source_tid':1,'native_oktmo':'79701000000','year':2024,'unit':'km','local_date':'2024-12-31','metadata_mapping_verified':True,'fullname_agrees_with_native_code':True,'temporal_eligible_halfopen_assumption':True,'indicator_id':'fixture UUID','source_period':'2024-12-30T21:00:00Z','value':3.}]))
   inv=r/'inventory.json';inv.write_text(json.dumps({'sources':sources}));out=r/'out';res=run(inv,out)
   self.assertTrue(res['checks']['base_sha_unchanged']);self.assertEqual(res['checks']['new_asof_2024_rows'],0)
   con=sqlite3.connect(out/'graph.sqlite')
   self.assertEqual(con.execute("select count(*) from observation where value=0").fetchone()[0],3)
   self.assertEqual(con.execute('select count(*) from missing_value').fetchone()[0],5)
   self.assertEqual(con.execute("select count(*) from loaded_quarantine where reason='duplicate_conflict'").fetchone()[0],10)
   self.assertEqual(con.execute("select count(*) from observation where provenance_class='observed'").fetchone()[0],1)
   self.assertEqual(con.execute("select count(*) from observation where indicator_id='mobility_purchase_distance_snapshot'").fetchone()[0],1)
   self.assertEqual(con.execute("select count(*) from loaded_quarantine where reason='source_end_year_boundary_ambiguous_or_expired'").fetchone()[0],5)

if __name__=='__main__':unittest.main()
