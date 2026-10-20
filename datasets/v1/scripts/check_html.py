from common import *
from html.parser import HTMLParser
import base64, subprocess, shutil

class Inspect(HTMLParser):
 def __init__(self):
  super().__init__(); self.scripts=[]; self.current=None; self.external=[]
 def handle_starttag(self,tag,attrs):
  a=dict(attrs)
  if tag=='script':
   assert 'src' not in a, 'External script dependency'
   self.current=[]
  if tag in ('img','link','iframe','video','audio','source'):
   for k in ('src','href'):
    if a.get(k) and not a[k].startswith(('data:','#')):self.external.append((tag,k,a[k]))
 def handle_data(self,data):
  if self.current is not None:self.current.append(data)
 def handle_endtag(self,tag):
  if tag=='script':self.scripts.append(''.join(self.current));self.current=None

def main():
 page=(ROOT/'review.html').read_text(encoding='utf-8');p=Inspect();p.feed(page)
 assert not p.external and len(p.scripts)==1
 js=p.scripts[0];r=subprocess.run([shutil.which('node'),'--check'],input=js,text=True,capture_output=True)
 assert r.returncode==0,r.stderr
 encoded=js.split('const D=',1)[1].split(';\nconst $=',1)[0];d=json.loads(encoded)
 assert len(d['tests'])==464 and len(d['pairs'])==49 and len(d['segments'])==9
 assert len(d['uncertain_groups'])==2 and len(d['assets'])==597
 for key,value in d['assets'].items():
  assert value.startswith('data:image/jpeg;base64,')
  raw=base64.b64decode(value.split(',',1)[1],validate=True)
  with Image.open(io.BytesIO(raw)) as im:im.verify()
 for t in d['tests']:assert t['asset'] in d['assets']
 for s in d['segments']:assert s['asset'] in d['assets']
 for pair in d['pairs']:assert pair['asset'] in d['assets']
 proof=ROOT/'runtime/standalone-proof';proof.mkdir(exist_ok=True)
 shutil.copyfile(ROOT/'review.html',proof/'review.html')
 assert sha(ROOT/'review.html')==sha(proof/'review.html')
 result=dict(status='STATIC_SELF_CONTAINMENT_AND_JAVASCRIPT_PASS',html_sha256=sha(ROOT/'review.html'),
  html_bytes=(ROOT/'review.html').stat().st_size,embedded_valid_jpegs=len(d['assets']),external_dependencies=p.external,
  javascript_syntax='node --check exit 0',standalone_copy=str(proof/'review.html'),standalone_copy_hash_identical=True)
 save(ROOT/'runtime/html-static-validation.json',result);print(json.dumps(result))

if __name__=='__main__':main()
