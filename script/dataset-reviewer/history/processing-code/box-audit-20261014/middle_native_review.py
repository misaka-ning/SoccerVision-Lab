import json, math
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
W=Path(__file__).parent
inv=json.loads((W/'inventory.json').read_text());by={r['filename']:r for r in inv};font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',13)
r=json.loads((W/'middle-tight-candidates.json').read_text());r=[x for x in r if x['evidence'].get('area_ratio',1)<.85 and x['evidence'].get('iou_with_original',0)>.65 and x['fit_confidence']>.35]
out=W/'middle-tight';out.mkdir(exist_ok=True); pages=[]
for off in range(0,len(r),16):
 page=Image.new('RGB',(1280,1280),'black');items=[]
 for i,x in enumerate(r[off:off+16]):
  im=Image.open(x['image_path']).convert('RGB');a=x['original_xyxy'];b=x['xyxy'];pad=max(10,max(a[2]-a[0],a[3]-a[1])*.35);box=[max(0,math.floor(min(a[0],b[0])-pad)),max(0,math.floor(min(a[1],b[1])-pad)),min(im.width,math.ceil(max(a[2],b[2])+pad)),min(im.height,math.ceil(max(a[3],b[3])+pad))];crop=im.crop(box);s=min(310/crop.width,278/crop.height);crop=crop.resize((round(crop.width*s),round(crop.height*s)),Image.Resampling.NEAREST);tile=Image.new('RGB',(320,320),'black');tile.paste(crop,((320-crop.width)//2,32));d=ImageDraw.Draw(tile);d.text((3,3),f'{off+i} {by[x["filename"]]["index"]} #{x["box_index"]} A={x["evidence"]["area_ratio"]:.2f}',font=font,fill='white');d.text((3,17),x['filename'].replace('video_4bec9c343db72928_frame_',''),font=font,fill='white')
  for xy,c in [(a,'orange'),(b,'cyan')]:d.rectangle([(xy[0]-box[0])*s+(320-crop.width)//2,(xy[1]-box[1])*s+32,(xy[2]-box[0])*s+(320-crop.width)//2,(xy[3]-box[1])*s+32],outline=c,width=2)
  page.paste(tile,((i%4)*320,(i//4)*320));items.append(x)
 p=out/f'page-{off//16:03}.jpg';page.save(p,quality=95);pages.append({'path':str(p),'items':items})
(W/'middle-tight-index.json').write_text(json.dumps(pages,ensure_ascii=False,indent=2))
frames=[9596,9663,9706,10198,10206,10222,10224,10304,10347,10350,10447,10501,10514,10522,10523,10537,10552,10554,10566,10573,10578,10664,10797,10808,10831,10940,10944,10956,10993,10995,11008,11371,11394,11709,11721,11829,11845,11856,11862,12096,12104,12109,12114,12122,12131,12139,12143,12152,12160,13904,13913,13949,14182,14190,14204,14476,14611,14622,14632,14634,14641,14648,14662,14686,14695,14706,14714,14716,15613,15622,15650,15978,15986,16008,16013,16638,16776,16818,17095,17345,17350,17385,17394]
rows=[x for x in inv if x['filename'].startswith('video_4bec9c343db72928_') and x.get('source_frame_idx') in frames];out=W/'middle-native';out.mkdir(exist_ok=True);pages=[]
for off in range(0,len(rows),6):
 page=Image.new('RGB',(1344,1236),'black');items=[]
 for i,row in enumerate(rows[off:off+6]):
  im=Image.open(row['image_path']).convert('RGB');d=ImageDraw.Draw(im)
  for xy in row['boxes']:d.rectangle(xy['xyxy'],outline='orange',width=1)
  tile=Image.new('RGB',(672,412),'black');tile.paste(im,(0,32));d=ImageDraw.Draw(tile);d.text((4,0),f'{row["index"]} {row["filename"].replace("video_4bec9c343db72928_frame_","")} B={len(row["boxes"])}',font=font,fill='white');d.text((4,16),'Native 672 x 376 ; orange = original',font=font,fill='white');page.paste(tile,((i%2)*672,(i//2)*412));items.append(row['index'])
 p=out/f'page-{off//6:03}.jpg';page.save(p,quality=97);pages.append({'path':str(p),'indices':items})
(W/'middle-native-index.json').write_text(json.dumps(pages,indent=2));print('tight',len(r),len(json.loads((W/'middle-tight-index.json').read_text())),'native',len(rows),len(pages))
