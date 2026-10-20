import json,pathlib,collections
B=pathlib.Path(__file__).parent;xs=json.load(open(B/'inventory.json'));mf=json.load(open(B/'roi_manifest.json'))
try:state=json.load(open(B/'observations.json'))
except FileNotFoundError:state={'scenes':{},'rois':{},'native':{}}
def scenes(page,positive_reason,exceptions=None):
 for i in range((page-1)*48,min(page*48,len(xs))):
  x=xs[i];s={'decision':'approve' if x['boxes'] else 'retain','reason':positive_reason if x['boxes'] else '全景中球可能藏在人物脚部或机器人后方，空标注不足以确认无球。','flags':{k:x['meta'][k] for k in ['Small','Occluded','Blurred','No Ball']}}
  state['scenes'][str(i)]=s
 for i,changes in (exceptions or {}).items():state['scenes'][str(i)].update(changes)
def scene(ids,decision,reason,**flags):
 for i in ids:
  state['scenes'][str(i)]['decision']=decision;state['scenes'][str(i)]['reason']=reason;state['scenes'][str(i)]['flags'].update(flags)
def rois(page,approvals,reason,retainreason='原生球框中的目标与脚或机器人相邻，外沿/遮挡或模糊边界不能高置信度确认。'):
 for m in mf:
  if m['roi_page']==page:
   state['rois'][str(m['local'])]={'decision':'approve_positive' if m['local'] in approvals else 'retain','reason':reason if m['local'] in approvals else retainreason,'page':page}
def save():
 json.dump(state,open(B/'observations.json','w'),ensure_ascii=False,indent=2)
def export():
 out=[]
 for i,x in enumerate(xs):
  s=state['scenes'].get(str(i));r=state['rois'].get(str(i))
  if not s:raise RuntimeError(f'unseen scene {i}')
  if x['boxes'] and not r:raise RuntimeError(f'unseen ROI {i}')
  ld=r['decision'] if r else s.get('label_decision', ('approve_negative' if s['decision']=='approve' and s['flags']['No Ball']=='1' else 'retain'))
  ev=[str(B/f'scene_{i//48+1:02d}.jpg')]
  if r:ev.append(str(B/f"roi_{r['page']:02d}.png"))
  ev+=state['native'].get(str(i),[])
  out.append({'filename':x['filename'],'index':x['index'],'scene_seen':True,'roi_seen':True if r else 'not_applicable','label_decision':ld,'scene_decision':s['decision'],'flags':s['flags'],'reason':(r['reason']+'；' if r else '')+s['reason'],'native_evidence':ev,'expected_label_sha256':x['label_sha256'],'expected_image_sha256':x['image_sha256'],'confidence_level':'high' if ld!='retain' and s['decision']=='approve' else 'uncertain'})
 json.dump(out,open(B/'decisions.json','w'),ensure_ascii=False,indent=2)
 print(collections.Counter(x['label_decision'] for x in out),collections.Counter(x['scene_decision'] for x in out))
if __name__=='__main__':export()
