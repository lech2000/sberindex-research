#!/usr/bin/env python3
"""Fetch the public nominal national monthly dataset with TLS and provenance.

A new live vintage is NOT a replacement for the frozen benchmark input.
Requires pyarrow. No raw data or credentials are automatically published.
"""
from pathlib import Path
from datetime import datetime,timezone
import argparse,base64,hashlib,json,subprocess,uuid
from download_sberindex_current import decode_sowa,table_from_page,pq

URL='https://sberindex.ru/api/sowa'
SLUG='consumer-spending'

def get(route):
 body={'SOWA':{'method':'GET','route':base64.b64encode(route.encode()).decode(),'data':{'type':'object','value':[]}}}
 response=subprocess.run(['/usr/bin/curl','--fail','--silent','--show-error','--max-time','90','--retry','2',URL,'-H','content-type: application/json','-H','RqUID: '+uuid.uuid4().hex,'-H','Referer: https://sberindex.ru/ru/dashboards/'+SLUG,'-H','User-Agent: aiOS2-SberIndex-research/1.0','-H','X-Language: ru','-H','Origin: https://sberindex.ru','--data-binary','@-'],input=json.dumps(body).encode(),capture_output=True,check=True)
 value=decode_sowa(json.loads(response.stdout)['SOWA']['data'])
 if isinstance(value,dict) and value.get('errors'):raise ValueError('Portal returned an API error')
 return value,response.stdout

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
 if a.out.exists():raise FileExistsError('Choose a new snapshot directory')
 page,wire=get('/dataset/v1/'+SLUG+'?limit=10000&offset=0')
 if len(page['data'])!=page['pagination']['total_records']:raise ValueError('Incomplete page; do not silently truncate')
 catalogue,_=get('/dataset/v1/list');meta=next(d for d in catalogue if d['dataset_id']==SLUG)
 meta={k:v for k,v in meta.items() if k not in ['chart','data']}
 translations,_=get('/i18n');footer=translations.get('ru',{}).get('footer',{})
 a.out.mkdir(parents=True,exist_ok=False)
 (a.out/'api-wire.json').write_bytes(wire)
 (a.out/'api-decoded.json').write_text(json.dumps(page,ensure_ascii=False,indent=2)+'\n')
 (a.out/'metadata.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
 pq.write_table(table_from_page(page['fields'],page['data']),a.out/'consumer-spending.parquet')
 manifest={'retrieved_at':datetime.now(timezone.utc).isoformat(),'source_url':'https://sberindex.ru/ru/dashboards/'+SLUG,'rows':len(page['data']),'historical_available_at':None,'historical_vintage':None,
 'license_status':'CC_BY_SA_NOT_CONFIRMED_FOR_THIS_DATASET','publisher_footer':footer.get('copyright'),'attribution':'Источник: СберИндекс, https://sberindex.ru/ru/dashboards/'+SLUG,
 'files':{q.name:hashlib.sha256(q.read_bytes()).hexdigest() for q in a.out.iterdir() if q.is_file()}}
 (a.out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(manifest,ensure_ascii=False))
if __name__=='__main__':main()
