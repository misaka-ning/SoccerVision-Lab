import json,collections
from pathlib import Path
p=Path(__file__).parent;a=json.loads((p/'inventory.json').read_text());m=json.loads((p/'manifest.json').read_text());n=json.loads((p/'notes.json').read_text())
assert set(n['opened_full'])==set(range(len(m['full'])))
assert set(n['opened_roi'])==set(range(max(int(Path(x['page']).stem.split('-')[-1]) for x in m['roi'])+1))
obs={}
for o in n['observations']:
 for i in o['locals']:obs[i]=o
assert set(obs)==set(range(250)),sorted(set(range(250))-set(obs))
fullmap={i:x['path'] for x in m['full'] for i in x['locals']}
rs=[]
for i,x in enumerate(a):
 o=obs[i];rois=[r for r in m['roi'] if r['local']==i];e=[fullmap[i]]
 for r in rois:
  path=r['page']
  if path not in e:e.append(path)
 d={'filename':x['filename'],'index':x['index'],'scene_seen':True,'roi_boxes_seen':sorted(r['box_index'] for r in rois),'action':o.get('action','keep'),'flags':dict(zip(('Small','Occluded','Blurred','No Ball'),o['flags'])),'scene_certain':o.get('certain',True),'confidence':'high' if o.get('certain',True) else 'uncertain','reason':o['reason'],'evidence':e,'expected_label_sha256':x['label_sha256'],'expected_image_sha256':x['image_sha256']}
 if i==27:
  d.update(action='replace',boxes_xyxy=[x['boxes'][0]['xyxy'],[9,95,58,133]],scene_certain=True,confidence='high',reason='全图确认两枚足球均有框；第二个后球旧框[12,105,60,145]明显切掉上方约10像素球冠且下方包入地毯阴影，按当前原生图可见球像素改为[9,95,58,133]，保留近球原框；球完整尺度约49像素，不记小目标，边缘低清柔化不等于方向性运动模糊。')
  d['evidence'] += [str(p/'details/n27-grid.png'),str(p/'details/n27-before-after.png')]
 rs.append(d)
(p/'proposals.json').write_text(json.dumps(rs,ensure_ascii=False,indent=2)+'\n')
s={'reviewer':'batch004_review2','images':250,'full_pages_seen':len(n['opened_full']),'roi_pages_seen':len(n['opened_roi']),'boxes_seen':len(m['roi']),'actions':dict(collections.Counter(x['action'] for x in rs)),'confidence':dict(collections.Counter(x['confidence'] for x in rs)),'flags':{k:sum(x['flags'][k]=='1' for x in rs) for k in ('Small','Occluded','Blurred','No Ball')},'opened_full':[x['path'] for x in m['full']],'opened_roi':[str(p/'roi'/('page-%03d.png'%i)) for i in n['opened_roi']],'detail_evidence':[str(x) for x in sorted((p/'details').glob('*.png'))],'pending_only':True,'canonical_dataset_written':False,'notes':'250原生全图及全部现框ROI已实际打开；空框不判无球，前景机器人挡住关键区域但无可辨球像素的样本保留可见性疑点；当前组一处第二球框明显漏上缘已提供原生前后对照修正，等待汇总二审。'}
(p/'summary.json').write_text(json.dumps(s,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in s.items() if not k.startswith('opened') and k!='detail_evidence'},ensure_ascii=False,indent=2))
