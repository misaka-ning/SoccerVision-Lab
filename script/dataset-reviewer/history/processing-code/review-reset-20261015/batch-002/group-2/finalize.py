import json
from pathlib import Path
from collections import Counter
p=Path(__file__).parent;s=json.loads((p/'notes.json').read_text());a=json.loads((p/'inventory.json').read_text());m=json.loads((p/'manifest.json').read_text())
assert sorted(s['full_pages'])==list(range(125));assert sorted(s['roi_pages'])==list(range(32));assert set(s['notes'])=={str(n) for n in range(250)}
s['details_opened']=[56,130,137,138,139,140,219,246,247,248]
s['notes']['56'].update(action='replace',confidence='high',scene_certain=True,boxes_xyxy=[[318,32,552,264]],reason='原生2倍图确认足球右端止于约x551，旧框x565多出约14px桌面，下端旧y268比球皮末端偏低。将四边候选改为[318,32,552,264]贴合可见球皮，保留旋转模糊分类，仍待用户复查。')
for n in [137,138,140]:s['notes'][str(n)].update(confidence='high',scene_certain=True,reason='原生2倍图确认左上手指与球缘有间隙或只接触，没有明确盖住球面，遮挡为0；足球旋转模糊明显，现框覆盖球体。')
s['notes']['139'].update(Occluded='1',confidence='high',scene_certain=True,reason='原生2倍图确认左上指尖跨过圆周边界遮住黑蓝球皮，遮挡为1；球体快速旋转，花纹有明确拖影，现框基本贴合。')
s['notes']['219'].update(action='keep',confidence='high',scene_certain=True,reason='原生2倍图复核，下缘独立白色细弧位于接触阴影之外的木地板上，判断为球在桌面的反光，不据此扩框。主球皮轮廓已被现框覆盖，球面缝线可辨，无真实前景遮挡。')
(p/'notes.json').write_text(json.dumps(s,ensure_ascii=False,indent=2))
fullmap={n:f['path'] for f in m['full'] for n in f['locals']};roimap={}
for q in m['roi']:roimap.setdefault(q['local'],[]).append(q)
out=[]
for n,r in enumerate(a):
 v=s['notes'][str(n)];ev=[fullmap[n]];qs=roimap.get(n,[])
 for q in qs:
  z=q['page'] if str(q['page']).startswith('/') else str(p/'roi'/str(q['page']))
  if z not in ev:ev.append(z)
 if n in s['details_opened']:ev.append(str(p/'details'/f'n{n:03d}.png'))
 out.append({'filename':r['filename'],'index':r['index'],'scene_seen':True,'roi_boxes_seen':[b['box_index'] for b in r['boxes']], 'action':v.get('action','keep'),'boxes_xyxy':v.get('boxes_xyxy',[b['xyxy'] for b in r['boxes']]),'flags':{k:v[k] for k in ['Small','Occluded','Blurred','No Ball']},'scene_certain':v.get('scene_certain',True),'confidence':v.get('confidence','high'),'reason':v['reason'],'evidence':ev,'expected_label_sha256':r['label_sha256'],'expected_image_sha256':r['image_sha256']})
for v in out:
 for ev in v['evidence']:assert Path(ev).is_file(),ev
assert len(out)==250;assert sum(len(v['roi_boxes_seen']) for v in out)==250
(p/'proposals.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
summary={'group':2,'images_seen':250,'boxes_seen':250,'all_full_pages_opened':[f['path'] for f in m['full']],'all_roi_pages_opened':[str(p/'roi'/f'page-{n:03d}.png') for n in s['roi_pages']], 'details_opened':[str(p/'details'/f'n{n:03d}.png') for n in s['details_opened']], 'full_pages_seen':125,'roi_pages_seen':32,'image_locals_seen':list(range(250)), 'actions':dict(Counter(v['action'] for v in out)), 'flags':{k:sum(v['flags'][k]=='1' for v in out) for k in ['Small','Occluded','Blurred','No Ball']}, 'uncertain':[v['filename'] for v in out if v['confidence']=='uncertain'],'replacements':[v['filename'] for v in out if v['action']=='replace'],'datasets_written':False,'method':'逐图原生全图与所有现框ROI目视，10张另开原生2倍局部；只生成暂存预审建议，未修改任何原始图片、label或metadata。'}
(p/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in summary.items() if k not in ['all_full_pages_opened','all_roi_pages_opened','image_locals_seen','details_opened']},ensure_ascii=False,indent=2))
