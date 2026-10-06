"""Compile allowlisted author Markdown/derived files for private-repo landing links."""
from pathlib import Path
import argparse,json,re,urllib.parse,posixpath,html,hashlib,subprocess,shutil

def main():
 a=argparse.ArgumentParser();a.add_argument('--repo',type=Path,required=True);a.add_argument('--out',type=Path,required=True);a.add_argument('--node',required=True);a.add_argument('--marked-module',required=True);a=a.parse_args();r=a.repo.resolve();out=a.out.resolve();assert not out.is_relative_to(r)
 def own(url,src):
  u=urllib.parse.urlsplit(html.unescape(url));p=urllib.parse.unquote(u.path)
  if u.scheme:
   prefix='/lech2000/sberindex-research/blob/'
   if u.netloc!='github.com' or not p.startswith(prefix):return None
   s=p[len(prefix):]
   if s.startswith('codex/sberindex-accelerated-public-20261003/'):return s[len('codex/sberindex-accelerated-public-20261003/'):]
   if re.match(r'[0-9a-f]{40}/',s):return s.split('/',1)[1]
   return ''
  if p.startswith('/sberindex-2026/reports/'):return p[len('/sberindex-2026/reports/'):].removesuffix('.html')+'.md' if p.endswith('.html') else p[len('/sberindex-2026/reports/'):]
  if not p:return None
  return posixpath.normpath(posixpath.join(posixpath.dirname(src),p))
 def allowed(p):return p and not p.startswith(('../','data/','integrations/','agents/','graph/','docs/evidence/')) and '/raw/' not in p and Path(p).suffix in ('.md','.json','.csv','.png','.svg') and (r/p).is_file() and (r/p).stat().st_size<1_500_000
 selected=set()
 for kind in ('economic-atlas','shock-radar'):
  src='presentation/'+kind+'/landing/index.html'
  for u in re.findall(r'href="([^"]+)"',(r/src).read_text()):
   p=own(u,src)
   if allowed(p):selected.add(p)
 todo=list(selected)
 while todo:
  src=todo.pop()
  if not src.endswith('.md'):continue
  for u in re.findall(r'\[[^\]]*\]\(([^\s)]+)',(r/src).read_text()):
   p=own(u,src)
   if allowed(p) and p not in selected:selected.add(p);todo.append(p)
 def pub(p):return p[:-3]+'.html' if p.endswith('.md') else p
 md=[{'path':p,'text':(r/p).read_text()} for p in sorted(selected) if p.endswith('.md')]
 node="import {pathToFileURL} from 'node:url';const {marked}=await import(pathToFileURL(process.argv[1]).href);let s='';for await(const c of process.stdin)s+=c;process.stdout.write(JSON.stringify(JSON.parse(s).map(x=>({path:x.path,body:marked.parse(x.text)}))));"
 rendered=json.loads(subprocess.check_output([a.node,'--input-type=module','-e',node,a.marked_module],input=json.dumps(md),text=True))
 dst=out/'reports';dst.mkdir(parents=True,exist_ok=True)
 css='body{margin:0;background:#0f1320;color:#e9edf5;font:17px/1.65 system-ui,sans-serif}main{max-width:1050px;margin:auto;padding:30px 24px 90px}a{color:#8ef0dd}h1,h2,h3{line-height:1.25;color:#fff;margin-top:1.7em}pre{overflow:auto;padding:16px;background:#182132;border:1px solid #39445b;font-size:14px}code{overflow-wrap:anywhere}table{display:block;max-width:100%;overflow:auto;border-collapse:collapse;font-size:14px}th,td{border:1px solid #3a455b;padding:8px;text-align:left}img{max-width:100%}nav,.meta,.restricted{font-size:14px;color:#adb8ce}.meta{overflow-wrap:anywhere;padding:12px;background:#182132;border-left:3px solid #8ef0dd}blockquote{border-left:3px solid #8898b1;padding-left:15px}li{margin:7px 0}'
 (dst/'report.css').write_text(css)
 for x in rendered:
  src=x['path'];body=x['body']
  def link(m):
   u=m.group(1);label=m.group(2);p=own(u,src)
   if p in selected:return '<a href="'+html.escape(posixpath.relpath(pub(p),posixpath.dirname(pub(src)) or '.'),quote=True)+'">'+label+'</a>'
   if p is not None:return '<span class="restricted">'+label+' (материал в репозитории с доступом)</span>'
   if urllib.parse.urlsplit(html.unescape(u)).scheme not in ('','http','https','mailto'):return label
   return m.group(0)
  body=re.sub(r'<a\s+href="([^"]+)"[^>]*>(.*?)</a>',link,body,flags=re.S)
  assert not re.search(r'<(?:script|iframe|object|embed)\b|on(?:load|error|click)\s*=',body,re.I)
  title=next((q.lstrip('# ').strip() for q in (r/src).read_text().splitlines() if q.startswith('# ')),src);source_sha=hashlib.sha256((r/src).read_bytes()).hexdigest();dest=dst/pub(src);dest.parent.mkdir(parents=True,exist_ok=True)
  cssrel=posixpath.relpath('report.css',posixpath.dirname(pub(src)) or '.')
  cssrel+='?v='+hashlib.sha256(css.encode()).hexdigest()[:12]
  dest.write_text('<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="script-src \'none\'; object-src \'none\'"><title>'+html.escape(title)+'</title><link rel="stylesheet" href="'+cssrel+'"><main><nav><a href="/sberindex-2026/economic-atlas/landing/">Атлас</a> · <a href="/sberindex-2026/shock-radar/landing/">Радар</a></nav><p class="meta">Авторский отчёт / производные результаты. Публичная копия авторского файла. Исходные датасеты здесь не размещаются; Git требует доступа. '+html.escape(src)+' · SHA256 '+source_sha+'</p>'+body+'</main></html>\n')
 for src in sorted(selected):
  if src.endswith('.md'):continue
  d=dst/src;d.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(r/src,d)
 landing=[]
 for kind in ('economic-atlas','shock-radar'):
  src='presentation/'+kind+'/landing/index.html';body=(r/src).read_text()
  def replace(m):
   p=own(m.group(1),src);assert p in selected,p;return 'href="/sberindex-2026/reports/'+pub(p)+'"'
  body,n=re.subn(r'href="(https://github.com/lech2000/sberindex-research/blob/[^"]+)"',replace,body)
  d=out/kind/'landing/index.html';d.parent.mkdir(parents=True,exist_ok=True);d.write_text(body);landing.append({'path':kind+'/landing/index.html','replaced_links':n})
 manifest=[];missing=[];links=0
 for f in sorted(out.rglob('*')):
  if not f.is_file():continue
  manifest.append({'path':f.relative_to(out).as_posix(),'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'bytes':f.stat().st_size})
  if f.suffix=='.html':
   for u in re.findall(r'(?:href|src)="([^"]+)"',f.read_text()):
    parsed=urllib.parse.urlsplit(html.unescape(u))
    if parsed.scheme or not parsed.path:continue
    if parsed.path.startswith('/sberindex-2026/reports/'):
     q=out/parsed.path[len('/sberindex-2026/'):]
    elif f.is_relative_to(dst) and not parsed.path.startswith('/'):
     q=f.parent/parsed.path
    else:continue
    links+=1
    if not q.is_file():missing.append([f.relative_to(out).as_posix(),u])
 assert not missing,missing
 # Restrict exported author text; no credentials/private input rows in this manifest.
 bad=[]
 for p in selected:
  if Path(p).suffix not in ('.md','.csv','.json'):continue
  t=(r/p).read_text()
  if re.search(r'ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----',t):bad.append(p)
 assert not bad,bad
 receipt={'source_commit':subprocess.check_output(['git','-C',str(r),'rev-parse','HEAD'],text=True).strip(),'compiler':'marked17.0.5, external self stylesheet, script-src none','source_allowlist':sorted(selected),'files':manifest,'public_internal_links_checked':links,'missing_internal_links':missing,'raw_inputs_published':False,'repository_visibility_changed':False,'landing_repairs':landing,'source_file_sha256':{p:hashlib.sha256((r/p).read_bytes()).hexdigest() for p in selected}}
 (out.parent/'public-manifest.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'files':len(manifest),'source_files':len(selected),'checked_internal_links':links,'bytes':sum(x['bytes'] for x in manifest),'landing':landing}))
if __name__=='__main__':main()
