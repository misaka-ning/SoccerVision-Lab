import json
from pathlib import Path
R=Path('dataset_processing/box-audit-20261014');a=json.load(open(R/'existing_audit.json'));inv=json.load(open(R/'inventory.json'))
props={888:[428,148,451,174],889:[416,148,439,174],890:[575,154,607,184],891:[561,154,592,183],894:[430,147,453,173],895:[417,147,442,173],897:[416,148,439,174],898:[603,159,638,186],899:[589,159,626,186],900:[514,149,546,179],901:[501,149,533,180]}
for i,b in props.items():
 r=a['images'][i];r['decision']='propose_box_adjustment_pending_manual_review';r['boxes'][0].update(tight_xyxy=b,decision='propose_adjust_pending_manual_review',reason='原生最近邻放大并按坐标刻度复核；原框在球两侧或下方包含可辨地面空隙，候选沿可见外缘收紧，保留模糊边缘。',confidence='medium',evidence=['native-auto-888-901.png']);r['uncertainty']=['moderate_motion_blur_boundary','all_assistant_changes_pending_manual_review'];r['boxes_xyxy']=[x['tight_xyxy'] or x['original_xyxy'] for x in r['boxes']];r['original_boxes_xyxy']=[x['original_xyxy'] for x in r['boxes']]
 if i==897:r['boxes'][0]['reason']='原生局部显示原框下方有较大地面空隙，上缘可能切入球的白色模糊边缘；候选上移上边并收紧左右、下边，待人工复核。'
(R/'existing_audit.json').write_text(json.dumps(a,ensure_ascii=False,indent=2))
