#!/usr/bin/env python3
"""Snapshot primary official event metadata; first_seen is never backdated."""
import argparse
from datetime import datetime,timezone
from html.parser import HTMLParser
import hashlib,json,re
from pathlib import Path
import subprocess

SOURCES=[
 ('orsk_mchs','https://56.mchs.gov.ru/deyatelnost/press-centr/novosti/5249015',['Орск','6 апреля 2024'], '2024-04-06', '08:42'),
 ('orenburg_weekly','https://56.mchs.gov.ru/deyatelnost/press-centr/vse_novosti/5252131',['10 апреля 2024','Оренбург','Новотроицк'], '2024-04-10',None),
 ('cbr_july','https://www.cbr.ru/press/pr/?file=26072024_133000key.htm',['26.07.2024 13:30:00','18,00%'], '2024-07-26','13:30'),
 ('cbr_september','https://www.cbr.ru/press/pr/?file=13092024_133000key.htm',['13.09.2024 13:30:00','19,00%'], '2024-09-13','13:30'),
 ('cbr_october','https://www.cbr.ru/press/pr/?file=25102024_133000key.htm',['25.10.2024 13:30:00','21,00%'], '2024-10-25','13:30'),
]
class Text(HTMLParser):
 def __init__(self):super().__init__();self.parts=[];self.hidden=0
 def handle_starttag(self,t,a):
  if t in ('script','style'):self.hidden+=1
 def handle_endtag(self,t):
  if t in ('script','style'):self.hidden=max(0,self.hidden-1)
 def handle_data(self,s):
  if not self.hidden and s.strip():self.parts.append(s.strip())

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--outdir',type=Path,required=True);a=p.parse_args()
 if a.outdir.exists():raise FileExistsError('new intake only')
 a.outdir.mkdir(parents=True);sources=[]
 for sid,url,tokens,date,time in SOURCES:
  dest=a.outdir/(sid+'.html')
  # System curl uses the OS trust store; TLS verification stays enabled.
  meta=subprocess.check_output(['curl','--fail','--silent','--show-error','--location','--connect-timeout','15','--max-time','45','--output',str(dest),'--write-out','%{json}',url],text=True)
  transport=json.loads(meta);raw=dest.read_bytes();final_url=transport['url_effective'];status=transport['http_code']
  if status!=200:raise ValueError('unexpected HTTP status')
  text=Text();text.feed(raw.decode('utf-8'));s=' '.join(' '.join(text.parts).replace('\xa0',' ').split())
  missing=[t for t in tokens if t not in s]
  if missing:raise ValueError(f'{sid}: content verification failed: {missing}')
  (a.outdir/(sid+'.html')).write_bytes(raw)
  sources.append({'source_id':sid,'url':url,'resolved_url':final_url,'http_status':status,
    'html_sha256':hashlib.sha256(raw).hexdigest(),'checked_at':datetime.now(timezone.utc).isoformat(),
    'source_claimed_published_date':date,'source_claimed_published_time':time,
    'source_timezone':'Europe/Moscow' if sid.startswith('cbr') else None,
    'checks':'official source body/date/rate or municipality tokens verified',
    'available_at':None,'vintage':None,'historical_asof_verified':False,
    'availability_basis':'dated official page read today; no contemporaneous archived snapshot acquired'})
  print(json.dumps({'source':sid,'status':'verified_today','published_date':date}),flush=True)
 byid={x['source_id']:x for x in sources}
 events=[]
 for eid,city,source in [('flood_orsk_2024','Орск','orsk_mchs'),('flood_orenburg_2024','Оренбург','orenburg_weekly'),('flood_novotroitsk_2024','Новотроицк','orenburg_weekly')]:
  x=byid[source];events.append({'event_id':eid,'entity_name':city,'scope':'municipality','event_type':'flood_documented',
   'event_month':'2024-04','exact_onset_date':None,'observation_date':x['source_claimed_published_date'],
   'source_id':source,'source_url':x['url'],'source_claimed_published_date':x['source_claimed_published_date'],
   'first_seen_at':x['checked_at'],'available_at':None,'historical_asof_verified':False,
   'event_family':'spring_flood_2024','is_economic_change_ground_truth':False})
 for month,new,old,sid in [('07',18,16,'cbr_july'),('09',19,18,'cbr_september'),('10',21,19,'cbr_october')]:
  x=byid[sid];events.append({'event_id':'cbr_rate_2024_'+month,'entity_name':'Банк России','scope':'national',
   'event_type':'rate_decision','event_date':x['source_claimed_published_date'],'event_month':'2024-'+month,
   'old_rate_pct':old,'new_rate_pct':new,'source_id':sid,'source_url':x['url'],
   'source_claimed_published_at':x['source_claimed_published_date']+'T13:30:00+03:00',
   'first_seen_at':x['checked_at'],'available_at':None,'historical_asof_verified':False,
   'is_economic_change_ground_truth':False})
 result={'checked_at':datetime.now(timezone.utc).isoformat(),'sources':sources,'events':events,
  'limits':['Sources establish real documented events, not ground truth of spending effects',
   'First seen is today; official publication dates are separate from unverified historical available_at/vintage',
   'Three local stories share one flood family; not three independent shock replications',
   'National rate decisions must not be duplicated as thousands of independent municipal events'],
  'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
 (a.outdir/'registry.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
if __name__=='__main__':main()
