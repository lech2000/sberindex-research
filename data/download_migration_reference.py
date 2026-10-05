"""Download only the CRC-checked 2023 member of the public indicator archive."""
import argparse,hashlib,json
from datetime import datetime,timezone
from pathlib import Path
from zipfile import ZipFile
from tochno_range_zip import HTTPRangeReader

URL='https://storage.yandexcloud.net/tochno-st-catalog/Rosstat/data_bdmo_118_v20250918/indicators/section31/data_Y48112023_112_v20250918.zip'
def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    if a.out.exists():raise FileExistsError('new download only')
    a.out.mkdir(parents=True);r=HTTPRangeReader(URL)
    with ZipFile(r) as z:
        matches=[x for x in z.infolist() if '_year2023_' in x.filename and x.filename.endswith('.parquet') and not x.filename.startswith('__MACOSX')]
        if len(matches)!=1:raise ValueError('year2023 member not unique')
        info=matches[0];path=a.out/'net-migration-2023.parquet'
        with z.open(info) as src,path.open('wb') as dest:
            while b:=src.read(1024*1024):dest.write(b)
        if path.stat().st_size!=info.file_size:raise ValueError('truncated selected member')
        receipt={'retrieved_at':datetime.now(timezone.utc).isoformat(),'url':URL,'archive_size':r.size,'etag':r.etag,
                 'member':info.filename,'member_bytes':info.file_size,'member_crc32':info.CRC,
                 'http_bytes':r.downloaded_bytes,'requests':r.requests,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        (a.out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt,indent=2))
if __name__=='__main__':main()
