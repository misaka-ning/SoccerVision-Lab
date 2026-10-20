import json,sys
from pathlib import Path
R=Path('dataset_processing/box-audit-20261014');out=R/'existing_audit.json';inv=[r for r in json.load(open(R/'inventory.json')) if not r['filename'].startswith('video_4bec9c343db72928_')]
if out.exists():a=json.load(open(out))
else:a={'scope':'all 1960 existing images excluding video_4bec9c343db72928_','reviewer':'assistant_visual_review','production_modified':False,'new_annotations_status':'pending_manual_review','reviewed_pages':{'full':[],'crops':[]},'images':[{'index':r['index'],'filename':r['filename'],'seen_full':False,'seen_crops':[],'decision':'unreviewed','uncertainty':[],'boxes':[{'box_index':i,'original_xyxy':b['xyxy'],'tight_xyxy':None,'decision':'unreviewed','reason':''} for i,b in enumerate(r['boxes'])]} for r in inv]}
kind=sys.argv[1];pages=list(map(int,sys.argv[2:]));mapping=json.load(open(R/'existing_contacts'/f'{kind}-map.json'))
for page in pages:
 if page not in a['reviewed_pages'][kind]:a['reviewed_pages'][kind].append(page)
 for e in mapping[page-1]['items']:
  row=a['images'][e['index']]
  if kind=='full':row['seen_full']=True;row['decision']='keep_original_pending_crop_review' if row['boxes'] else ('retain_visibility_review' if inv[e['index']]['meta']['annotation_status']=='needs_visibility_review' else 'visually_no_ball_on_full_scene')
  else:
   row['seen_crops'].append(e['box_index']);b=row['boxes'][e['box_index']]
   if b['decision']=='unreviewed':b['decision']='keep_original';b['reason']='视觉检查原框局部，未见明确需要改框的证据；原有状态不升级。'
   if row['seen_full'] and len(set(row['seen_crops']))==len(row['boxes']) and not row['decision'].startswith('propose'):row['decision']='keep_original'
out.write_text(json.dumps(a,ensure_ascii=False,indent=2))
print('reviewed full',len(a['reviewed_pages']['full']),'crop',len(a['reviewed_pages']['crops']))
