import json
from pathlib import Path
ROOT=Path('/home/misaka/workspace/dataset_processing/box-audit-20261014')
INV=json.loads((ROOT/'inventory.json').read_text()); INDEX=json.loads((ROOT/'review-new/index.json').read_text())
PATH=ROOT/'review-last-decisions.json'
if PATH.exists(): LEDGER=json.loads(PATH.read_text())
else:
 LEDGER={r['filename']:{'index':r['index'],'filename':r['filename'],'scene_seen':False,'roi_seen':False,'review_status':'not_reviewed','action':'retain_pending_review','boxes_xyxy':[b['xyxy'] for b in r['boxes']],'reason':'','source_scene_pages':[],'source_roi_pages':[],'proposal_status':'pending_root_safety_review','automatically_approved':False} for r in INV if r['index'] in set(INDEX['groups']['last']['indices'])}

def mark_pages(kind,pages):
 for page in pages:
  rec=next(x for x in INDEX['pages'] if x['group']=='last' and x['kind']==kind and x['page']==page)
  for name in rec.get('filenames',[x['filename'] for x in rec.get('items',[])]):
   row=LEDGER[name];row[kind+'_seen' if kind=='scene' else 'roi_seen']=True
   field='source_scene_pages' if kind=='scene' else 'source_roi_pages'
   if page not in row[field]:row[field].append(page)
   if row['review_status']=='not_reviewed': row['review_status']='contact_sheet_screened'
   if not row['reason']:row['reason']='已逐图查看联系页；未发现需明确替换的框，原框作为待审保留。'

def change(index,boxes,reason,status='native_verified_correction_proposal'):
 r=INV[index];row=LEDGER[r['filename']];row.update({'action':'replace','boxes_xyxy':boxes,'reason':reason,'review_status':status,'native_image_reviewed':True,'annotation_status_before':r['meta']['annotation_status']})

def uncertain(index,reason):
 r=INV[index];row=LEDGER[r['filename']];row.update({'review_status':'uncertain_visible_extent','action':'retain_pending_review','reason':reason})

def save():
 PATH.write_text(json.dumps(LEDGER,ensure_ascii=False,indent=2)+'\n')
 if __name__=='__main__':print(len(LEDGER))
