import json,math
from pathlib import Path
W=Path(__file__).parent;inv=json.loads((W/'inventory.json').read_text());by={r['index']:r for r in inv};new=[r for r in inv if r['filename'].startswith('video_4bec9c343db72928_')][2146:4292]
# Explicit decisions from the actually opened full-image and native ROI pages.
false=[4186,4187,4216,4405,4421,4423,4424,4425,4434,4435,4436,4437,4441,4463,4499,4503,4508,4509,4536,4537,4538,4539,4540,4742,4743,5654,5658,5660,6227]
manual={
4204:[145,135,176,166],4205:[144,134,175,167],
4341:[317,246,334,269],4342:[289,264,305,286],
4550:[230,244,265,275],4552:[242,235,277,266],4554:[274,211,310,245],
4653:[344,247,437,365],4658:[231,285,266,316],
4744:[344,35,380,81],4745:[335,35,372,81],
4774:[426,128,454,176],4775:[404,128,434,176],
4780:[331,365,370,376],4781:[310,365,349,376],
4853:[644,122,672,181],
4846:[350,264,505,376],4847:[285,259,429,376],
4848:[442,304,569,376],4849:[380,304,506,376],
4854:[442,265,504,319],4855:[409,266,465,319],
4856:[345,172,407,241],4857:[308,170,372,239],
4858:[337,73,414,144],4859:[306,73,380,144],
4860:[294,110,362,176],4861:[258,106,336,174],
4862:[356,156,409,210],4863:[330,156,382,211],
5310:[144,255,161,278],5315:[140,253,158,276],5323:[110,250,128,266],
5762:[352,252,407,317],5763:[330,252,385,317],
5764:[404,261,430,299],5765:[377,262,402,299],
5772:[289,337,350,376],5773:[266,336,331,376],
5868:[564,285,588,314],5869:[551,285,572,314],
6026:[487,0,672,290],
6062:[283,340,320,376],6063:[255,340,293,376],
6074:[53,317,121,376],6075:[14,317,82,376],
6148:[296,358,339,376],6149:[269,358,312,376],
6226:[611,360,650,376],6228:[331,362,352,376],6229:[290,353,320,376]
}
proposals={};decisions=[]
for r in new:
 i=r['index'];act='retain';reason='Full scene and every original box ROI visually inspected; retain existing box where no unambiguous boundary correction is supported.';boxes=[b['xyxy'] for b in r['boxes']]
 if i in false:boxes=[];act='replace';reason='Native full-image and ROI review confirmed that the candidate targets a toy, shoe, floor sticker, robot light or pillar rather than a football. Remove the false box; absence is not a confirmed negative.'
 if i in manual:boxes=[manual[i]];act='replace';reason='Native per-eye visual review: locate the visible football and align four sides with its visible outer boundary; exclude hand, shadow and unrelated equipment. Truncated balls use only visible image extent. Pending human review.'
 if act=='replace':proposals[r['filename']]={'filename':r['filename'],'split':r['split'],'expected_label_sha256':r['label_sha256'],'boxes_xyxy':boxes,'action':'correct_false_positive_or_missing_ball','native_visual_review':True,'reason':reason,'source':'root_full_scene_and_native_roi_visual_review','index':i}
 decisions.append({'filename':r['filename'],'index':i,'scene_seen':True,'roi_seen':bool(r['boxes']),'action':act,'boxes_xyxy':boxes,'reason':reason,'source_scene_page':(i-new[0]['index'])//48,'review_status':'assistant_visual_audit_not_human_approval'})
# Only the native comparison that cleanly removes the arm was accepted. Other ellipse hypotheses were rejected/held where they cut actual panels or blur.
r=json.loads((W/'middle-tight-index.json').read_text());flat=[x for p in r for x in p['items']];x=flat[89];a=x['xyxy'];row=next(t for t in inv if t['filename']==x['filename']);b=[max(0,a[0]-1),max(0,a[1]-1),min(row['width'],a[2]+1),min(row['height'],a[3]+1)]
proposals[row['filename']]={'filename':row['filename'],'split':row['split'],'expected_label_sha256':row['label_sha256'],'boxes_xyxy':[b],'action':'correct_false_positive_or_missing_ball','native_visual_review':True,'reason':'Native comparison confirms excess right margin is hand/forearm; tighten to complete dark football outer silhouette, retaining image clipping. Pending human review.','source':'root_native_comparison','index':row['index']}
for d in decisions:
 if d['filename']==row['filename']:d.update(action='replace',boxes_xyxy=[b],reason=proposals[row['filename']]['reason'])
(W/'review-middle-decisions.json').write_text(json.dumps(decisions,ensure_ascii=False,indent=2));(W/'middle-corrections-proposals.json').write_text(json.dumps(list(proposals.values()),ensure_ascii=False,indent=2));print(len(proposals),'proposals')
# Native full image overlays for each proposed frame, with old orange and new green.
from PIL import Image,ImageDraw,ImageFont
font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',13);out=W/'middle-proposed';out.mkdir(exist_ok=True);pp=list(proposals.values());pages=[]
for off in range(0,len(pp),6):
 page=Image.new('RGB',(1344,1236),'black');items=[]
 for k,p in enumerate(pp[off:off+6]):
  row=by[p['index']];im=Image.open(row['image_path']).convert('RGB');d=ImageDraw.Draw(im)
  for b in row['boxes']:d.rectangle(b['xyxy'],outline='orange',width=1)
  for b in p['boxes_xyxy']:d.rectangle(b,outline='#00ff70',width=1)
  tile=Image.new('RGB',(672,412),'black');tile.paste(im,(0,32));d=ImageDraw.Draw(tile);d.text((3,1),str(p['index'])+' '+p['filename'].replace('video_4bec9c343db72928_frame_',''),font=font,fill='white');d.text((3,16),'orange=old ; green=proposed ; native pixels',font=font,fill='white');page.paste(tile,((k%2)*672,(k//2)*412));items.append(p['index'])
 path=out/f'page-{off//6:03}.jpg';page.save(path,quality=97);pages.append({'path':str(path),'indices':items})
(W/'middle-proposed-index.json').write_text(json.dumps(pages,indent=2));print('preview',len(pages))
