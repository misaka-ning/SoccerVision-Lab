import json
from pathlib import Path
from collections import Counter
W=Path(__file__).resolve().parent
items=json.load(open(W/'inventory.json')); manifest=json.load(open(W/'manifest.json')); notes=json.load(open(W/'notes.json'))
notes['opened_native']=[str(p) for p in sorted((W/'native').glob('*.png'))]
json.dump(notes,open(W/'notes.json','w'),ensure_ascii=False,indent=2)
negative=set(range(22,36))|set(range(114,128))|{150,151,161,163,165,167,183}|set(range(168,182))|set(range(246,250))
manual=set(range(74,80))|{82,83,160,162,166}; visibility={80,81}
small=set(range(40,50))|set(range(66,80))|set(range(82,92))|set(range(154,160))|{160,162,164,166,182}|set(range(184,198))
occluded=set(range(12,17))|{18}|set(range(82,96))|set(range(132,138))|{148,149,160,162,164,166,182}|set(range(184,188))
blurred=set(range(4,8))|{10,11,20,21}|set(range(36,82))|{92,93,112,113,114,115,116,117,152,153,232,233,234,235,242,243,244,245}
small_uncertain={0,1,10,11,36,37,38,39,50,51,52,53,92,93}|set(range(96,106))|{196,197}
box_uncertain={10,11,20,21,56,57,58,59,62,63,64,65,68,69,70,71,72,73,182,232,233,234,235,242,243,244,245}
segments=[
 (0,3,'门边白线附近可见一只蓝白星纹球，未见额外球或脚轮误检，候选框覆盖单一球体。'),
 (4,7,'白线旁近球可见，转动场景和球纹外缘存在方向性软拖影，原框未拆分球面花纹。'),
 (8,9,'近处单一星纹球完整，球纹与外轮廓可分辨，无前景遮挡。'),
 (10,11,'全景和四倍器械局部均见两只真实球；远球位于灰色横梁前，近球裁底，两框对应不同球，未见脚轮误检。'),
 (12,16,'近大球裁底，黑色前景机器人圆头/机件明确覆盖球的左下或下方球面。'),
 (17,17,'近大球裁底，黑色圆头停在球左侧外缘，未见明确覆盖球面；仅裁底不计遮挡。'),
 (18,18,'底边近大球可见，黑色前景机件压住左下球面；同时存在底边裁切。'),
 (19,19,'底边近大球残片可见，左侧机件接近但未见明确覆盖可见球面；裁边不计遮挡。'),
 (20,21,'底边仍可见大球顶部及星纹残片，旁边灰色物体是鞋；球裁底且有运动拖影，不能由残片判为Small。'),
 (22,35,'完整场景只见鞋、裤腿、手臂、门/器械脚轮，已检查地面和底边，无可见足球。'),
 (36,39,'右侧白线旁有真实星纹球，部分被画面右边缘裁切，未见前景挡球；球与场景有运动软拖影。'),
 (40,49,'通道地面可见单一远处星纹小球，球/场景有方向性运动软化，未见额外球。'),
 (50,55,'通道中央真实球可见，球体与全图有运动拖影，原框未把阴影或球纹拆成第二目标。'),
 (56,59,'通道近球可见；n56–57仅露底边球上半，n58–59全球有强斜向运动拖影，保留原候选。'),
 (60,65,'通道近大球可见，n62–63裁底；球/全图运动拖影存在，未见前景挡球或漏掉其他球。'),
 (66,73,'远处地面/椅脚旁小球真实可见，已逐框看无框与红框ROI；有运动模糊，球未与鞋或脚轮混淆。'),
 (74,79,'三倍背景局部确认椅脚旁/双腿间后方有蓝白小球，当前零框属漏标；强模糊和邻近椅脚使可见边界不可靠，需用户补框，暂不编造坐标。'),
 (80,81,'三倍局部中后方位置被裤腿和鞋遮住，无法确认是否仍有可见球残片；保留空候选并待可见性复查，No Ball=0。'),
 (82,83,'三倍局部确认伸手下方有蓝白小球，手覆盖球的上部；当前无框，球边界软化及手部遮挡使可靠边框不可确定，需人工补框。'),
 (84,91,'人手持单一远处小球，手指/手掌明确覆盖球上缘或左缘；低像素本身不当作运动模糊。'),
 (92,93,'前进过程中手持球有明显垂直运动拖影，手掌覆盖球上部；完整球尺度邻近40px。'),
 (94,95,'弯腰放球时近球可见，手覆盖球上缘；球体大于40px，未见额外球。'),
 (96,105,'地面单一星纹球，附近两只鞋与球分离；原框覆盖球体且未拆花纹，无明确球体运动拖影。'),
 (106,113,'地面近球单一可见，鞋/器械未盖住球；n112–113裁底且球与场景运动软化，其余球纹可分辨。'),
 (114,127,'原生全景地面、门口及机件边缘已检查，未见可见足球；鞋和裤腿不作为球框。'),
 (128,131,'门口近球真实可见，n128–129裁底，n130–131完整；不把裁边算作前景遮挡。'),
 (132,137,'鞋底明确压住球上缘右部，球其余外轮廓和星纹清楚；这是前景遮挡，不是仅在球旁接触。'),
 (138,147,'地面单一完整球，鞋已离开球面，无前景遮挡；球面花纹与暗色地面阴影均未拆框。'),
 (148,149,'底边近球可见，鞋底盖住球上缘，另有画面底裁；完整球明显大于40px。'),
 (150,151,'抬起的鞋和门口地面完整可见，球已在画面外，未见可见球残片。'),
 (152,153,'脚旁真实近球有明显运动拖影，鞋与可见球体分离，保留单球候选。'),
 (154,159,'门边可见单一小球及其地面阴影，门框线在球后方，未见明确前景遮挡。'),
 (160,160,'四倍柜边局部确认有球的左侧可见残片，右侧被白柜遮住，当前无框；严重遮挡和软边不宜推测完整圆形，需人工补框。'),
 (161,161,'四倍柜边局部只见柜体和后方门框线，球在此目没有可见残片；按完整图实际可见性建议No Ball=1。'),
 (162,162,'四倍柜边局部确认白柜左侧露出蓝灰球面，当前无框属漏标；柜体挡住右半球，边缘软化需用户补框。'),
 (163,163,'四倍柜边局部仅见柜体/门框，无可见球面；不根据另一目猜测球框，建议No Ball=1。'),
 (164,164,'ROI及四倍局部确认候选为柜边真实小球，白柜遮住球右部，保留现有可见范围候选。'),
 (165,165,'四倍柜边局部没有可见足球，仅柜体边缘与地面；建议No Ball=1。'),
 (166,166,'四倍柜边局部确认真球露在柜体左侧，当前零框属漏标；右缘柜体覆盖及低清软边使边框不可靠，需人工补框。'),
 (167,167,'四倍柜边局部只见柜体和地面，无可见足球；建议No Ball=1。'),
 (168,181,'完整图检查门垫、桌椅支腿、左右底边及人脚，没有可见足球。'),
 (182,182,'柜体左侧可见窄球面残片，白柜明确遮住球右部；保留原候选，不推测柜后完整形状。'),
 (183,183,'四倍柜边局部只见鞋和柜边，球在此目没有可见球面；完整图未见其他球，建议No Ball=1。'),
 (184,187,'门垫旁小球可见，鞋底跨在球上缘并挡住部分球面，遮挡成立；无第二个球。'),
 (188,195,'门垫旁完整小球，鞋已移离球上缘；暗色轮廓仍能与球下地面阴影区分。'),
 (196,197,'门垫旁完整球可见，鞋与球分离，球约38px长边邻近40px临界，候选未拆花纹。'),
 (198,205,'门垫旁近大球完整可见，暗色星纹并非第二球，现框贴合外轮廓。'),
 (206,207,'底边仅见近大球顶部及星纹，属于画面裁切，不计Occluded或Small。'),
 (208,231,'门垫旁单一近球，球面花纹与外轮廓可辨，四角背景为矩形框正常现象；n228–231仅底边裁切，未见前景挡球。'),
 (232,235,'右侧近球被画面裁边，球面和边缘存在运动软拖影；鞋未覆盖球，不机械缩小模糊框。'),
 (236,241,'两脚附近近球完整可见，鞋停在球侧或球后方，未见明确盖住球面；背景展示柜经四倍局部确认是非球异形器件。'),
 (242,243,'脚旁球可见，球纹及轮廓有横向运动模糊；鞋仅接近球，未见明确前景挡球。'),
 (244,245,'左边缘近大球可见并有明显运动拖影，左侧为画面裁切，不能标成前景遮挡或小球。'),
 (246,249,'地面、门垫、底边均无可见球；展示柜内物体经四倍局部确认是非球异形器件，鞋亦非球。')]
def desc(n):
    return next(s for lo,hi,s in segments if lo<=n<=hi)
roi_by_local={n:[] for n in range(250)}
for r in manifest['roi']:roi_by_local[r['local']].append(r)
proposals=[]
for n,item in enumerate(items):
    fs={'Small':str(int(n in small)),'Occluded':str(int(n in occluded)),'Blurred':str(int(n in blurred)),'No Ball':str(int(n in negative))}
    action='needs_manual_bbox_annotation' if n in manual else ('needs_visibility_review' if n in visibility else 'keep')
    certain=n not in (manual|visibility|small_uncertain)
    reason=desc(n)
    if n in small_uncertain:reason+=' Small临界或裁边/运动软边影响完整尺度判断，先按当前最合理值记录，场景分类待用户复查。'
    if n in box_uncertain:reason+=' 球边界受裁切/强运动软化影响，原候选保留供用户检查，不编造精确圆形。'
    reason+=f' 本图建议四项为Small={fs["Small"]}、Occluded={fs["Occluded"]}、Blurred={fs["Blurred"]}、No Ball={fs["No Ball"]}。仅助手预审，仍待用户复查通过。'
    evidence=[str(W/'full'/f'page-{n//6:02d}.png')]+sorted(set(r['page'] for r in roi_by_local[n]))
    native=[]
    if n in range(12,16):native=['bottom-0.png']
    elif n in range(16,20):native=['bottom-1.png']
    elif n in range(74,78):native=['missing-0.png']
    elif n in range(78,82):native=['missing-1.png']
    elif n in {82,83}:native=['missing-2.png']
    elif n in range(160,164):native=['cabinet-0.png']
    elif n in range(164,168):native=['cabinet-1.png']
    elif n in {182,183}:native=['cabinet-2.png']
    if n in {62,63,234,235}:native+=[f'bounds-{n}.png']
    if n in {238,240,242,244,246,248}:native+=['shelf.png']
    if n in {10,11}:native+=['double-ball.png']
    evidence += [str(W/'native'/p) for p in native]
    proposals.append({'filename':item['filename'],'index':item['index'],'scene_seen':True,'roi_boxes_seen':sorted(r['box_index'] for r in roi_by_local[n]),'action':action,'boxes_xyxy':[[round(v,5) for v in b['xyxy']] for b in item['boxes']],'flags':fs,'scene_certain':certain,'confidence':'high' if certain and n not in box_uncertain else 'uncertain','reason':reason,'evidence':evidence,'expected_label_sha256':item['label_sha256'],'expected_image_sha256':item['image_sha256']})
assert len(proposals)==250
for n,(p,it) in enumerate(zip(proposals,items)):
    assert p['roi_boxes_seen']==[b['box_index'] for b in it['boxes']],n
    assert len(p['boxes_xyxy'])==len(it['boxes'])
    assert all(Path(e).is_file() for e in p['evidence'])
json.dump(proposals,open(W/'proposals.json','w'),ensure_ascii=False,indent=2)
summary={'group':'batch-001/group-2','opened_full':notes['opened_full'],'opened_ROI':notes['opened_roi'],'opened_roi':notes['opened_roi'],'opened_native':notes['opened_native'],'images_seen':250,'full_pages_seen':42,'roi_pages_seen':24,'native_pages_seen':len(notes['opened_native']),'boxes_seen':186,'all_images_covered':True,'all_original_boxes_covered':True,'actions':dict(Counter(p['action'] for p in proposals)),'flags':{k:sum(p['flags'][k]=='1' for p in proposals) for k in ['Small','Occluded','Blurred','No Ball']},'scene_uncertain':sum(not p['scene_certain'] for p in proposals),'confidence_uncertain':sum(p['confidence']=='uncertain' for p in proposals),'manual_bbox_filenames':[p['filename'] for p in proposals if p['action']=='needs_manual_bbox_annotation'],'visibility_review_filenames':[p['filename'] for p in proposals if p['action']=='needs_visibility_review'],'small_threshold':'完整球长边按672宽原生尺度约<=40px；临界与大球残片不机械设1','review_status':'全部仍为待用户审核的助手候选预审；keep不是通过','writes':'仅本group暂存目录；无正式datasets写入','replacement_boxes':0}
json.dump(summary,open(W/'summary.json','w'),ensure_ascii=False,indent=2)
print(json.dumps({k:v for k,v in summary.items() if not k.startswith('opened')},ensure_ascii=False,indent=2))
