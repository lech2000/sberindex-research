"""Fetch a public SberIndex dataset metadata record without inventing name joins."""
import argparse,base64,json,subprocess
from pathlib import Path
from download_sberindex_current import decode_sowa

def main():
    p=argparse.ArgumentParser();p.add_argument('--dataset',default='indeks-mobilnosti');p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    if a.out.exists():raise FileExistsError('new snapshot only')
    body={'SOWA':{'method':'GET','route':base64.b64encode(b'/dataset/v1/list').decode(),'data':{'type':'object','value':[]}}}
    r=subprocess.run(['/usr/bin/curl','--fail','--silent','--show-error','--max-time','60','https://sberindex.ru/api/sowa','-H','Content-Type: application/json','-H','X-Language: ru','-H','Referer: https://sberindex.ru/ru/dashboards/'+a.dataset,'--data-binary','@-'],input=json.dumps(body).encode(),capture_output=True,check=True)
    decoded=decode_sowa(json.loads(r.stdout)['SOWA']['data']);matches=[x for x in decoded if x.get('dataset_id')==a.dataset]
    if len(matches)!=1:raise ValueError('dataset metadata missing/not unique')
    kept={k:v for k,v in matches[0].items() if k not in ['chart','data','defaultSlices','generalSettings']}
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(kept,ensure_ascii=False,indent=2))
    print(json.dumps({'dataset':a.dataset,'dimensions':[x['code'] for x in kept['dimensions']]}))
if __name__=='__main__':main()
