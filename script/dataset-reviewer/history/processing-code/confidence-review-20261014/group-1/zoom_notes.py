from review_notes import *
def update(nums,detail,scene=None,label=None,flags=None):
 for n in nums:
  x=notes[str(n)];x['detail']=detail
  if scene:x['scene']=scene
  if label:x['label']=label
  if flags:x['flags']=flags
negative={'Small':'0','Occluded':'0','Blurred':'0','No Ball':'1'}
update(range(591,595),'原生全景及手部放大见白灰物有双柄/U形外轮廓和黑色中心，属于手持控制器，非球体；地板、桌脚、人物脚下与四边未见足球。背景与地面清晰，确认为无球场景。',scene='approve',flags=negative)
update(range(595,605),'远处红衣人手持白灰物放大呈双柄/U形控制器，缺少可靠连续球面；现有人工球框已确认并保护，球/控制器身份与现有有球场景存在冲突，保留场景重新核查。',scene='retain')
update(range(605,609),'原生全景检查地板、底边与桌脚；远处人物手侧白灰物放大呈控制器柄状，但片段过小，无法可靠排除手侧另有球体，保留场景身份核查。',scene='retain')
update([611,612],'原生全景及展示架放大见白灰反光板/拼块与机械支架相连；分辨率不足以可靠确定是否还有球体，现人工negative与候选冲突保留核查，不据此更改已有框状态。',scene='retain')
update([697],'原生全景及机器人左下放大以支架、金属结构和人物鞋为主；局部灰白片段身份仍不够可靠，人工negative保持，场景保留可见性复核。',scene='retain')
update([822,823],'原生全景及脚下放大确认下缘白灰形状为运动鞋，鞋外地面、下边界与侧边没有足球弧面；整图存在明显移动拖影，因此为Blurred与No Ball，Small/Occluded均不适用。',scene='approve',flags={'Small':'0','Occluded':'0','Blurred':'1','No Ball':'1'})
update([824],'原生全景及脚下放大在下边界见极小白色弧形，与运动鞋尖相邻；不足以可靠区分鞋片段与足球顶盖，保留场景可见性核查并保护人工negative状态。',scene='retain')
update([890,891],'原生机器人侧后放大有白灰弧状片段，与机器结构、人物鞋附近混合；球体身份和可见边界不可靠，保护人工negative，保留场景冲突复核。',scene='retain')
update([1157,1163],'原生全景及左缘放大确认画面边缘只有圆柱底座、白色运动鞋与地毯；未见与鞋分离的足球弧面。四边、人物脚下及远处地面均核验无球，整图清晰，可确认为无球空标。',scene='approve',label='approve_negative',flags=negative)
update([1159,1165],'原生全景及左缘放大见最左边界露出极小白灰弧面，与柱底/白鞋分离但裁切过少；足球残片身份与完整边界不能可靠确认，保留empty补框/可见性审核。',scene='retain',label='retain')
update(range(1226,1230),'原生全景及机器人脚下放大见脚间粉白/灰白弧状小片段，与方形脚壳、金属连接件混合；不能可靠排除被机器人遮住的足球残片，空label保留可见性及补框审核。',scene='retain',label='retain')
mp=json.load(open(D+'/zooms/map.json'))
for p in range(5):
 path=D+f'/zooms/page-{p:02}.png'
 vals=mp[p]
 # map stores review tile records or index list
 ns=vals['n'] if isinstance(vals,dict) and 'n' in vals else vals
 if isinstance(ns,list):
  for v in ns:
   n=v if isinstance(v,int) else v['n']
   notes[str(n)]['native_evidence']=sorted(set(notes[str(n)].get('native_evidence',[])+[path]))
ledger['zoom']=[D+f'/zooms/page-{p:02}.png' for p in range(5)]
save()
