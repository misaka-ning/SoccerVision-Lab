import json,hashlib,collections
from pathlib import Path
from PIL import Image,ImageDraw
R=Path('dataset_processing/box-audit-20261014');inv=json.load(open(R/'inventory.json'));rows=json.load(open(R/'middle-missing-extra-inventory.json'))
P={5530:[30,337,60,369],5531:[0,334,44,370],5532:[36,335,69,367],5533:[17,335,53,367],5534:[43,337,66,365],5535:[25,335,49,365],5536:[18,329,61,366],5537:[0,329,45,365],5538:[19,325,63,363],5539:[1,325,47,363],5540:[18,326,64,366],5541:[1,326,48,366],5542:[19,321,66,360],5543:[1,321,49,360],5544:[18,325,64,365],5545:[1,325,48,365],5546:[14,328,59,368],5547:[0,328,44,368],5548:[15,328,60,366],5549:[0,328,44,366],5550:[18,326,64,367],5551:[1,326,46,367],5552:[17,327,63,367],5553:[0,327,47,367],5554:[17,325,62,365],5555:[0,325,46,365],5556:[17,325,61,365],5557:[0,325,45,365],5558:[17,326,62,364],5559:[0,326,46,364],5628:[2,341,48,376],5632:[5,338,53,376],5633:[0,336,32,376],5634:[6,338,53,376],5646:[8,344,53,376],5648:[12,362,51,376],5649:[0,361,30,376],5650:[14,368,46,376],5651:[0,368,29,376],5657:[0,369,29,376],5669:[0,346,32,376],5671:[0,346,31,376],5672:[9,339,55,376],5706:[33,320,77,359],5707:[16,320,60,360],5722:[282,254,315,291],5723:[266,254,300,292],5724:[246,319,280,357],5725:[229,319,263,357],5726:[245,325,279,364],5727:[229,324,263,363],5728:[243,327,278,368],5729:[227,327,262,368],5730:[253,334,288,376],5731:[236,334,271,376],5732:[269,355,309,376],5733:[251,354,291,376],8186:[18,326,63,365],8187:[0,326,45,365]}
props=[];coverage=[]
for j,r in enumerate(rows):
 i=r['index'];b=P.get(i);e={'index':i,'filename':r['filename'],'image_path':r['image_path'],'expected_label_sha256':r['label_sha256'],'expected_image_sha256':r['image_sha256'],'original_boxes_xyxy':[],'boxes_xyxy':[b] if b else [],'reviewed_full_scene':True,'reviewed_native_roi':True,'full_evidence':f'middle-extra-native-full-{j//4+1:02}.jpg','roi_evidence':f'middle-extra-native-roi-{j//12+1:02}.png','source_frame_idx':r['source_frame_idx'],'eye':r['eye'],'annotation_status_before':r['meta']['annotation_status']}
 if b:
  assert 0<=b[0]<b[2]<=r['width'] and 0<=b[1]<b[3]<=r['height'];e.update(decision='add_missing_visible_ball_pending_manual_review',annotation_status_after='auto_label_needs_review',label_review_required=1,ball_presence_confidence='high',boundary_confidence='medium',No_Ball=0,reason='原生全景及坐标刻度最近邻局部确认足球黑白面板与可见轮廓；空标签漏掉该球。候选仅包可见像素，排除地毯投影，不补全图外/被挡部分。',uncertainty=['all_assistant_boxes_pending_manual_review','source_boundary_is_soft'])
  if i<=5535:e['uncertainty'].append('partially_occluded_by_foreground_leg_or_shoe')
  if b[0]==0 or b[3]==376:e['uncertainty'].append('image_edge_clipped_visible_extent_only')
  if i in (5648,5649,5650,5651,5657,5732,5733):e['uncertainty'].append('thin_visible_ball_cap_pending_close_manual_review')
  if i in (5730,5731):e['uncertainty'].append('foot_occludes_upper_ball_boundary')
  props.append(e)
 else:e.update(decision='retain_empty_pending_visibility_review',reason='原生检查未见可靠完整可见球；部分帧仅图边数像素灰白片或球完全在画面外/被遮挡，无法可靠给候选框。',uncertainty=['no_reliable_visible_ball_boundary_in_this_image']);e['No_Ball']=None
 coverage.append(e)
(R/'middle-missing-extra.json').write_text(json.dumps(props,ensure_ascii=False,indent=2));(R/'middle-missing-extra-coverage.json').write_text(json.dumps({'inventory_sha256':hashlib.sha256((R/'inventory.json').read_bytes()).hexdigest(),'images':coverage,'summary':{'empty_images_native_reviewed':len(rows),'confirmed_missing_visible_ball_proposals':len(props),'retain_empty_pending_visibility_review':len(rows)-len(props),'full_pages_seen':20,'native_roi_pages_seen':7}},ensure_ascii=False,indent=2))
for st in range(0,len(props),12):
 o=Image.new('RGB',(1024,690),'#202020');d=ImageDraw.Draw(o)
 for j,e in enumerate(props[st:st+12]):
  r=inv[e['index']];b=e['boxes_xyxy'][0];im=Image.open(r['image_path']).convert('RGB');roi=[max(0,b[0]-12),max(0,b[1]-12),min(im.width,b[2]+12),min(im.height,b[3]+12)];c=im.crop(roi);sc=min(256/c.width,185/c.height);c=c.resize((round(c.width*sc),round(c.height*sc)),Image.Resampling.NEAREST);dd=ImageDraw.Draw(c);dd.rectangle([(b[0]-roi[0])*sc,(b[1]-roi[1])*sc,(b[2]-roi[0])*sc,(b[3]-roi[1])*sc],outline='lime',width=1);xx=j%4*256;yy=j//4*230;o.paste(c,(xx,yy+38));d.text((xx+2,yy+2),f"{e['index']} f{e['source_frame_idx']} {e['eye']}",fill='white');d.text((xx+2,yy+18),str(b),fill='white')
 o.save(R/f'middle-extra-proposal-verified-{st//12+1:02}.png')
print('proposals',len(props),'exceptions',len(rows)-len(props))
