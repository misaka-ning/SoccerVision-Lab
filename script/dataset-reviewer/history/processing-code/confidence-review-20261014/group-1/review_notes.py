import json,os,math,datetime
D=os.path.dirname(__file__); inventory=json.load(open(D+'/inventory.json')); P=D+'/notes.json'
notes=json.load(open(P)) if os.path.exists(P) else {}; ledger=json.load(open(D+'/opened.json')) if os.path.exists(D+'/opened.json') else {'full':[],'roi':[],'native':[]}
def add(nums,detail,scene='approve',label='auto',flags=None):
 for n in nums:
  notes[str(n)]={'detail':detail,'scene':scene,'label':label,'flags':flags}
def seq(a,b,*args,**kw): add(range(a,b+1),*args,**kw)
def opened(full=[],roi=[],native=[]):
 for k,v in [('full',full),('roi',roi),('native',native)]:
  ledger[k]=sorted(set(ledger[k]+v))
def save():
 json.dump(notes,open(P,'w'),ensure_ascii=False,indent=2);json.dump(ledger,open(D+'/opened.json','w'),ensure_ascii=False,indent=2)
def native(pages):
 mp=json.load(open(D+'/empty-native/map.json'))
 for p in pages:
  path=mp[p]['path'];ledger['native'].append(path)
  for n in mp[p]['n']:
   notes[str(n)]['native_evidence']=[path]
 ledger['native']=sorted(set(ledger['native']))
