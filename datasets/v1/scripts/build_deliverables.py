from common import *
import base64,html
from datetime import datetime,timezone

def main():
 v=load(ROOT/'verification.json');assert v['status']=='PASS_FOR_ALLOCATION_AND_LOADING'
 records=load(ROOT/'manifest.json')['records'];by={r['filename']:r for r in records};stats=load(ROOT/'statistics.json')
 source={r['filename']:r for r in load(ROOT/'analysis/source_inventory.json')}
 segments=load(ROOT/'analysis/segments.json');blocks=load(ROOT/'analysis/heldout_blocks.json')
 tests=sorted([r for r in records if r['usage']=='test'],key=lambda r:r['source_seconds'])
 pairs=load(ROOT/'analysis/final_pairs_to_visually_review.json');observations={p['pair_id']:p for p in load(ROOT/'analysis/final_pair_visual_observations.json')}
 uncertain=load(ROOT/'analysis/uncertain_groups.json');withdrawn=load(ROOT/'analysis/withdrawn_representatives.json')
 assets={}
 def embed_file(key,path):assets[key]='data:image/jpeg;base64,'+base64.b64encode(Path(path).read_bytes()).decode()
 names={r['filename'] for r in tests}|{p[k] for p in pairs for k in ['test_image','other_image']}|{r['filename'] for r in withdrawn}
 for name in sorted(names):
  r=dict(source[name]);r['source_image']=by[name]['image'];im=tile(r,416,234)
  buffer=io.BytesIO();im.save(buffer,format='JPEG',quality=80);assets['img:'+name]='data:image/jpeg;base64,'+base64.b64encode(buffer.getvalue()).decode()
 for s in segments:
  embed_file('segment:'+s['segment_id'],ROOT/f'evidence/segment-{s["segment_id"]}.jpg')
 for p in pairs:embed_file('pair:'+p['pair_id'],ROOT/p['evidence_path'])
 initial=load(ROOT/'analysis/pairs_to_visually_review.json');initial_by={p['pair_id']:p for p in initial}
 for g in uncertain:
  g['representatives']=[r['filename'] for r in withdrawn if r['review_group']==g['group_id']]
  for pid in g['evidence_pair_ids']:
   embed_file('pair:'+pid,ROOT/initial_by[pid]['evidence_path'])
 def compact(r):
  return dict(filename=r['filename'],seconds=r['source_seconds'],frame=r['source_frame_idx'],eye=r['eye'],segment=r['segment_id'],
   block=r['heldout_block_id'],flags=[f for f in FLAGS if r[f]],box_count=r['box_count'],image_path=r['image'],
   session=r['session_id'],usage=r['usage'],asset='img:'+r['filename'])
 segment_ui=[]
 for s in segments:
  rr=[r for r in records if r['segment_id']==s['segment_id']]
  segment_ui.append(dict(s,test_count=sum(r['usage']=='test' for r in rr),heldout_unused_count=sum(r['usage']=='heldout_unused' for r in rr),asset='segment:'+s['segment_id']))
 pair_ui=[]
 for p in pairs:
  pair_ui.append(dict(p,asset='pair:'+p['pair_id'],assistant_observation=observations[p['pair_id']]['assistant_observation']))
 dataset=dict(version_id=ROOT.name,config=str(ROOT/'dataset.yaml'),counts=v['counts'],statistics=stats,segments=segment_ui,blocks=blocks,
  tests=[compact(r) for r in tests],pairs=pair_ui,uncertain_groups=uncertain,assets=assets,
  test_source_frames=len(tests),test_core_segments=len({r['segment_id'] for r in tests}),test_contiguous_blocks=len({r['heldout_block_id'] for r in tests}),
  physical_test_sessions=1,limitation='同场次片段留出：Test与Train共享18:15:31这一真实采集场次；片段和左右目不是独立场次。',
  current_risk='464张代表图已做跨Train/Val检索；49个最终重点图片对已实际查看（41对复用同图观察、8对新增），无法确认的2组26张候选代表图已退出Test。')
 payload=json.dumps(dataset,ensure_ascii=False,separators=(',',':')).replace('<',chr(92)+'u003c')
 page='''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>足球数据集 · 同场次片段留出复核</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f3f5f8;color:#172438;font:15px/1.55 system-ui,sans-serif}header,main{max-width:1440px;margin:auto;padding:20px}header{background:white;border-bottom:1px solid #d3dbe6}h1{font-size:26px;margin:0 0 8px}h2{font-size:20px}p{margin:8px 0}.warning{background:#fff3db;border-left:4px solid #ba7a12;padding:11px 14px;margin:12px 0}.stats{display:flex;flex-wrap:wrap;gap:10px;margin:15px 0}.stat{background:#eaf0f7;border:1px solid #d4ddea;padding:10px 18px;border-radius:7px;min-width:135px}.stat b{font-size:24px;display:block}.tabs,.toolbar,.pager{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:12px 0}.tabs button.active{background:#2356a0;color:white}.toolbar{position:sticky;top:0;background:#f3f5f8;padding:10px 0;z-index:2}button,input,select{font:inherit;border:1px solid #aebbd0;border-radius:5px;padding:7px 10px;background:white}button{cursor:pointer}button:disabled{opacity:.4;cursor:default}input[type=search]{min-width:270px;flex:1}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}.card,.segment,.pair,.group{background:white;border:1px solid #d3dbe6;border-radius:7px;overflow:hidden}.card img{width:100%;display:block;cursor:zoom-in}.caption{padding:9px}.filename{font-size:11px;overflow-wrap:anywhere;color:#536477}.flags{color:#945013;font-weight:600}.segment,.pair,.group{margin:14px 0;padding:14px}.evidence{width:100%;max-height:900px;object-fit:contain;cursor:zoom-in;background:#e9edf3}.pair .evidence{max-height:550px}.small{font-size:13px;color:#536477}.count{padding:8px 0;color:#536477}.timeline{width:100%;height:76px;display:block}table{border-collapse:collapse;width:100%;font-size:14px}td,th{text-align:left;padding:8px;border-bottom:1px solid #d9e1ec}code{word-break:break-all}dialog{max-width:95vw;max-height:95vh;border:1px solid #aab8cc;border-radius:8px;padding:14px}dialog img{max-width:90vw;max-height:76vh;object-fit:contain;display:block}dialog::backdrop{background:#132030bb}[hidden]{display:none!important}.group-thumbs{display:flex;gap:8px;flex-wrap:wrap}.group-thumbs img{width:200px;cursor:zoom-in}.note{background:#eef4fb;padding:10px;border-radius:4px;margin:9px 0}@media(max-width:700px){header,main{padding:12px}h1{font-size:22px}.toolbar{position:static}.stats .stat{min-width:100px;padding:7px}.grid{grid-template-columns:repeat(2,minmax(0,1fr))}input[type=search]{min-width:180px}}
</style></head><body><header><h1>足球检测数据集 · 同场次片段留出复核</h1><p id="subtitle"></p><div class="warning" id="limit"></div><div class="stats" id="stats"></div><p class="small">这是单文件离线页面：数据、脚本、样式和预览图均已内嵌。绿色框来自原有label；本轮未改框或场景。点击图片可放大内嵌预览。</p><p class="small">新配置：<code id="config"></code></p></header><main>
<div id="timeline"></div><div class="tabs"><button data-tab="test" class="active">Test样本</button><button data-tab="segments">片段与缓冲</button><button data-tab="pairs">最高风险图片对</button><button data-tab="groups">待回收复核 · 2组</button><button data-tab="facts">来源与评估口径</button></div>
<section id="test"><div class="toolbar"><select id="segmentFilter" aria-label="Test片段"><option value="all">全部Test片段</option></select><select id="sceneFilter" aria-label="困难场景"><option value="all">全部场景</option><option value="ordinary">普通清晰有球</option><option>Small</option><option>Occluded</option><option>Blurred</option><option>No Ball</option></select><input id="search" type="search" aria-label="搜索图片" placeholder="搜索文件名、帧号或时间"><button id="prev">上一页</button><span id="page"></span><button id="next">下一页</button></div><div id="testCount" class="count"></div><div id="testGrid" class="grid"></div><div class="pager"><button id="prev2">上一页</button><span id="page2"></span><button id="next2">下一页</button></div></section>
<section id="segments" hidden><p>CORE为候选留出核心；BUFF为根据动作起止、镜头转换和后续相似对检查设置的缓冲。S02/S03衔接为一个连续保留块。S05整段暂不进入Test。缓冲距离不是独立性证明。</p><div id="segmentCards"></div></section>
<section id="pairs" hidden><p id="pairNote"></p><div class="toolbar"><select id="pairRole" aria-label="对照集合"><option value="all">Train与Val全部</option><option value="train">只看Train</option><option value="val">只看Val</option></select><button id="pairPrev">上一页</button><span id="pairPage"></span><button id="pairNext">下一页</button></div><div id="pairCards"></div></section>
<section id="groups" hidden><p>以下两组已保守留在heldout_unused，当前正式Test不依赖你的判断。仅当希望将它们回收为Test时再复核并建立新版本；本页选择只保存在本机，不修改图片、label或manifest。</p><button id="export">导出本机组复核记录</button><div id="groupCards"></div></section>
<section id="facts" hidden><h2>来源事实</h2><p>用户已确认10月13日三段录像来自三个独立采集场次；legacy回忆来自另两个场次，本版整批合并为一个保守分组。所有来源均没有足球场环境。本轮无需进一步拆分legacy。</p><h2>Test应如何命名</h2><p>同场次片段留出测试。Train仍包含18:15:31的其他片段，Test真实采集场次只有1；464个源帧时刻、8个核心片段和7个含Test的连续留出块均不等于独立试验数。后续独立采集Test使用future_independent_session_test单独来源标记和清单，分别报告。</p><h2>抽样比例与标签</h2><p>局部多信号去冗余、完整动作阶段和对困难场景的覆盖会改变原视频比例。本页图级标签原样保留，多球图片不能把图级Small/Occluded/Blurred自动赋给每个球。场景正负分母及变化详见下表。</p><div id="distribution"></div><h2>旧权重曝光</h2><p>已有权重是否用过本次留出图片，训练成员历史为未知。现在移动或复制图片不能撤销已发生的训练曝光。正式比较应从从未训练过这些留出核心及缓冲图片的初始化重新训练；版本目录提供架构随机初始化配置示例，本轮未训练任何模型。</p><h2>边界</h2><p>文件与解码像素精确重复为0，已记录的关联没有跨正式分集。全局特征、哈希及有限人工对照仍不能证明所有未记录动作绝对独立。此版本通过分配与加载核验，不等于独立场次泛化验证。</p></section>
</main><dialog id="zoom"><button id="closeZoom">关闭</button><p id="zoomTitle"></p><img id="zoomImage" alt="放大内嵌证据"></dialog><script>const D=__PAYLOAD__;
const $=id=>document.getElementById(id),E=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const CN={Small:'小目标',Occluded:'遮挡',Blurred:'运动模糊','No Ball':'无球'};const time=t=>{let m=Math.floor(t/60),s=(t%60).toFixed(1);return String(m).padStart(2,'0')+':'+s.padStart(4,'0')};
let page=0,pairPage=0;let decisions={};try{decisions=JSON.parse(localStorage.getItem(D.version_id+'-group-review')||'{}')}catch(e){}
$('subtitle').textContent=D.version_id+' · 8148张可用图片全部有去向；原250张隔离样本未进入任何正式集合。';$('limit').textContent=D.limitation;$('config').textContent=D.config;
$('stats').innerHTML=Object.entries(D.counts).map(([k,v])=>'<div class="stat">'+E(k)+'<b>'+v+'</b></div>').join('');
let svg='<svg class="timeline" viewBox="0 0 1300 76" aria-label="18:15:31录像留出时间线"><rect x="20" y="20" width="1260" height="20" fill="#c6d5e8"/>';
D.blocks.forEach(b=>svg+='<rect x="'+(20+b.start_seconds/1620*1260)+'" y="20" width="'+((b.end_seconds-b.start_seconds)/1620*1260)+'" height="20" fill="#dfb366"/>');
D.segments.forEach(s=>svg+='<rect x="'+(20+s.start_seconds/1620*1260)+'" y="20" width="'+((s.end_seconds-s.start_seconds)/1620*1260)+'" height="20" fill="'+(s.test_count?'#5784b9':'#a2a5a9')+'"/>');
D.tests.forEach(r=>svg+='<circle cx="'+(20+r.seconds/1620*1260)+'" cy="30" r="1.3" fill="#922d35"/>');
for(let t=0;t<=1620;t+=180)svg+='<text x="'+(20+t/1620*1260)+'" y="60" font-size="12">'+Math.floor(t/60)+':00</text>';svg+='</svg>';$('timeline').innerHTML='<div class="small">18:15:31源视频时间线：浅色Train候选；黄色缓冲；蓝色留出核心；红点Test代表；灰色待复核核心。所有区段仍属同一场次。</div>'+svg;
for(let s of D.segments.filter(s=>s.test_count))$('segmentFilter').insertAdjacentHTML('beforeend','<option>'+E(s.segment_id)+'</option>');
function testRender(){let seg=$('segmentFilter').value,scene=$('sceneFilter').value,q=$('search').value.toLowerCase();let r=D.tests.filter(r=>(seg==='all'||r.segment===seg)&&(scene==='all'||scene==='ordinary'&&r.box_count>0&&!r.flags.length||r.flags.includes(scene))&&(!q||(r.filename+' '+r.frame+' '+time(r.seconds)).toLowerCase().includes(q)));let pages=Math.max(1,Math.ceil(r.length/50));page=Math.min(page,pages-1);$('testCount').textContent='当前筛选 '+r.length+' / '+D.tests.length+' 张；每页50张。Test时刻'+D.test_source_frames+'，核心片段'+D.test_core_segments+'，连续留出块'+D.test_contiguous_blocks+'，真实场次1。';$('page').textContent=$('page2').textContent='第 '+(page+1)+' / '+pages+' 页';$('prev').disabled=$('prev2').disabled=page===0;$('next').disabled=$('next2').disabled=page===pages-1;
$('testGrid').innerHTML=r.slice(page*50,(page+1)*50).map(r=>'<article class="card"><img loading="lazy" src="'+D.assets[r.asset]+'" data-asset="'+E(r.asset)+'" data-caption="'+E(r.filename)+'" alt="'+E(r.filename)+'"><div class="caption"><b>'+time(r.seconds)+' · '+E(r.segment)+' · '+E(r.eye)+'</b><div class="flags">'+(r.flags.length?r.flags.map(f=>CN[f]).join('、'):'普通清晰有球')+'</div><div>'+r.box_count+'个球框</div><div class="filename">'+E(r.filename)+'</div></div></article>').join('');}
for(let id of ['segmentFilter','sceneFilter','search'])$(id).addEventListener(id==='search'?'input':'change',()=>{page=0;testRender()});for(let id of ['prev','prev2'])$(id).onclick=()=>{page--;testRender()};for(let id of ['next','next2'])$(id).onclick=()=>{page++;testRender()};
$('segmentCards').innerHTML=D.segments.map(s=>'<article class="segment"><h2>'+E(s.segment_id)+' · '+time(s.start_seconds)+'–'+time(s.end_seconds)+'</h2><p>Test '+s.test_count+'张；核心未用 '+s.heldout_unused_count+'张；缓冲外沿 '+time(s.buffer_start_seconds)+'–'+time(s.buffer_end_seconds)+'</p><p>'+E(s.boundary_reason)+'</p><img loading="lazy" class="evidence" data-asset="'+s.asset+'" data-caption="'+s.segment_id+' 联系图" src="'+D.assets[s.asset]+'" alt="'+s.segment_id+'片段联系图"></article>').join('');
$('pairNote').textContent=D.current_risk+' 下面展示最终重点对照，数值为筛查证据，不能单独证明事件相同或独立。';
function pairRender(){let rr=D.pairs.filter(p=>$('pairRole').value==='all'||p.other_role===$('pairRole').value),pages=Math.max(1,Math.ceil(rr.length/8));pairPage=Math.min(pairPage,pages-1);$('pairPage').textContent='第 '+(pairPage+1)+' / '+pages+' 页 · '+rr.length+'对';$('pairPrev').disabled=pairPage===0;$('pairNext').disabled=pairPage===pages-1;$('pairCards').innerHTML=rr.slice(pairPage*8,(pairPage+1)*8).map(p=>'<article class="pair"><b>'+p.pair_id+' · '+p.segment_id+' Test ↔ '+p.other_role+'</b><p class="small">cosine '+p.cosine.toFixed(4)+' · pHash '+p.phash+' · dHash '+p.dhash+' · SSIM128 '+p.ssim.toFixed(3)+' · 筛查优先级 '+p.risk+'</p><img loading="lazy" class="evidence" src="'+D.assets[p.asset]+'" data-asset="'+p.asset+'" data-caption="'+p.pair_id+'" alt="'+p.pair_id+'图片对"><div class="note">助手观察：'+E(p.assistant_observation)+'</div></article>').join('');}
$('pairRole').onchange=()=>{pairPage=0;pairRender()};$('pairPrev').onclick=()=>{pairPage--;pairRender()};$('pairNext').onclick=()=>{pairPage++;pairRender()};
$('groupCards').innerHTML=D.uncertain_groups.map(g=>'<article class="group"><h2>'+g.group_id+' · '+g.segment_id+' · '+g.withdrawn_initial_representatives+'张候选代表</h2><p>'+E(g.reason)+'</p><select aria-label="'+g.group_id+'复核结果" data-group="'+g.group_id+'"><option value="">待复核（留空）</option><option value="keep_unused">继续暂不使用</option><option value="recover_new_version">可在新版本回收</option><option value="uncertain">仍不确定</option></select><div class="group-thumbs">'+g.representatives.map(n=>'<img loading="lazy" src="'+D.assets['img:'+n]+'" data-asset="'+E('img:'+n)+'" data-caption="'+E(n)+'" alt="'+E(n)+'">').join('')+'</div>'+g.evidence_pair_ids.slice(0,2).map(pid=>'<img loading="lazy" class="evidence" src="'+D.assets['pair:'+pid]+'" data-asset="pair:'+pid+'" data-caption="'+pid+' 未决证据" alt="'+pid+' 未决图片对">').join('')+'</article>').join('');
document.querySelectorAll('[data-group]').forEach(x=>{x.value=decisions[x.dataset.group]||'';x.onchange=()=>{decisions[x.dataset.group]=x.value;try{localStorage.setItem(D.version_id+'-group-review',JSON.stringify(decisions))}catch(e){}}});
$('export').onclick=()=>{let a=document.createElement('a'),blob=new Blob([JSON.stringify({version:D.version_id,group_review:decisions},null,2)],{type:'application/json'});a.href=URL.createObjectURL(blob);a.download=D.version_id+'-review.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)};
let table='<table><tr><th>用途</th><th>图片</th><th>有球</th><th>无球</th><th>框</th><th>Small</th><th>Occluded</th><th>Blurred</th></tr>';Object.entries(D.statistics).forEach(([k,s])=>table+='<tr><td>'+k+'</td><td>'+s.images+'</td><td>'+s.positive_images+'</td><td>'+s.negative_images+'</td><td>'+s.boxes+'</td><td>'+s.scenes.Small.images+'</td><td>'+s.scenes.Occluded.images+'</td><td>'+s.scenes.Blurred.images+'</td></tr>');$('distribution').innerHTML=table+'</table>';
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{document.querySelectorAll('[data-tab]').forEach(x=>x.classList.toggle('active',x===b));['test','segments','pairs','groups','facts'].forEach(id=>$(id).hidden=id!==b.dataset.tab)});
document.addEventListener('click',e=>{let x=e.target.closest('[data-asset]');if(!x)return;$('zoomImage').src=D.assets[x.dataset.asset];$('zoomTitle').textContent=x.dataset.caption||'';$('zoom').showModal()});$('closeZoom').onclick=()=>$('zoom').close();testRender();pairRender();
</script></body></html>'''.replace('__PAYLOAD__',payload)
 (ROOT/'review.html').write_text(page,encoding='utf-8')
 # Concise, numerical report and direct operational instructions.
 def pct(n,d):return f'{100*n/d:.1f}%'
 lines=['# 足球检测数据集：同场次片段留出 v1','',
  '**已落地并通过分配、字节完整性、真实YOLODataset及批次读取核验。该结论不是独立场次泛化审计PASS。**','',
  f'版本：`{ROOT}`。原datasets目录、metadata、旧分集和250项隔离数据均保留；新版本使用独立物理副本，不是软链或硬链。','',
  '| 用途 | 图片 | 有球图 | 无球图 | 足球框 | Small | Occluded | Blurred |','|---|---:|---:|---:|---:|---:|---:|---:|']
 for k,s in stats.items():lines.append(f'| {k} | {s["images"]} | {s["positive_images"]} | {s["negative_images"]} | {s["boxes"]} | {s["scenes"]["Small"]["images"]} | {s["scenes"]["Occluded"]["images"]} | {s["scenes"]["Blurred"]["images"]} |')
 lines+=['',f'五类合计8148张；原250张排除样本不在其中。Train保留原6925候选中的{len([r for r in records if r["usage"]=="train"])}张（{pct(stats["train"]["images"],6925)}），含全部713张legacy。Val1154+69=1223张完全锁定。新增暂不使用的2115张=buffer755+heldout_unused1360，均保留，不能与原排除250张混同。','',
  '## 选择与分母','',
  '按全片时间联系图、镜头搬动/转向、球与人脚/机器人动作阶段先划定连续留出外沿，再在核心内按多信号状态变化去冗余。起步9段核心，经保守撤回G02后，正式Test覆盖8个核心片段、7个含Test的连续保留块；总共8个保留块含一个未用于Test的待复核块。S02/S03衔接为同一保留块，不把两个编号当独立事件。','',
  'Test464张=464个源帧时刻，真实测试采集场次1，与Train共享18:15:31场次。并未估计独立动作数或有效独立样本数。三段录像的独立场次关系由用户本轮明确确认；legacy回忆的另外两场合为一个保守分组，不再追查逐图归属。所有数据没有足球场环境，旧相反推测不再采用。','',
  '选目规则：奇数片段优先left，偶数片段优先right；只有该目已排除或缺失时才使用另一可用目，未根据检测分数或清晰度选目。另一目随完整片段保留在heldout_unused，不进Train/Val；辅助配对清单在lists/test_stereo_pairs.csv，两目不算两个独立事件。','',
  '初始工程预算400–600，最终464张。核心内采用时间、已有pHash/dHash、归一化全局特征、SSIM及现有框位置变化共同减少连续冗余；对静止背景不按每帧计数，对短暂遮挡/模糊和较大状态变化保留较密代表。另26张初选代表因G01/G02不确定而退出Test。未运行检测预测，未按模型成绩挑选。','',
  '| 核心段 | 源视频时间 | 缓冲外沿 | Test代表 | 核心未用 |','|---|---|---|---:|---:|']
 for s in segment_ui:lines.append(f'| {s["segment_id"]} | {stamp(s["start_seconds"])}–{stamp(s["end_seconds"])} | {stamp(s["buffer_start_seconds"])}–{stamp(s["buffer_end_seconds"])} | {s["test_count"]} | {s["heldout_unused_count"]} |')
 video=[r for r in records if r['source']=='181531'];test_stats=stats['test']
 lines+=['','缓冲外沿逐段依据见analysis/segments.json。实际图像抽样后的Test–Train最近时间间隔为'+f'{v["nearest_train_time_gap_seconds"]["min"]:.3f}秒，中位数{v["nearest_train_time_gap_seconds"]["median"]:.1f}秒；这些数值不是独立性证明。尤其S03连续机位提前保护，S04完整远球跟随留到转向门口，S08覆盖球滚离后的完整尾部。','',
  '| 场景 | 181531全部6212图比例 | Test比例 | Test有球图 / 无球图 |','|---|---:|---:|---:|']
 for f in FLAGS:
  s=test_stats['scenes'][f];lines.append(f'| {f} | {pct(sum(r[f] for r in video),len(video))} | {pct(s["images"],len(tests))} | {s["positive_images"]} / {s["negative_images"]} |')
 lines+=['',f'Test另有普通清晰有球{test_stats["ordinary_clear_positive"]}张、多球{test_stats["multiball_images"]}张。以上是图级多标签，不能直接把一幅多球图的Small/Occluded/Blurred赋给每个球。No Ball图不进入足球Recall分母。抽样使静止无球比例下降、运动过程比例上升，不能把该分层测试比例当连续机器人运行的自然发生率。','',
  '## 复核、解决与限制','',
  '复用了既有8148个MobileNetV3-small/ImageNet1K576维L2特征、pHash/dHash及灰图，未重新训练特征模型。原文件SHA逐项一致后，复用原解码像素哈希。最终464查询对Train/Val分别做精确内积分块top8，加BK树p≤12/d≤10候选，再对7616候选计算SSIM128×72。阈值是复核优先级，既不证明独立，也不因SSIM低就否决关联。','',
  '实际查看了全片9页概览、9段边界联系图及其修订上下文。图片对共90个不同照片组合有实际观察（初轮57、第二轮新增25、末轮新增8）；最终49个重点对中41对复用同照片观察、8对新增。初筛数值未出现high不代表绝对无近重复。G01/G02保守撤回、连续机位/远球尾部扩大保护，是基于实际看图和时序，而非单阈值。','',
  'G01有6张初选代表，涉及相机抬起前与刚放下的前后关联；G02有20张初选代表，涉及远球/机器人重置前后关系。两组当前都不进Test，不需要先等用户裁决；仅回收时复核。原人工球框、场景和审核状态未覆盖。','',
  '完整性核验：8148图五类去向无交集且无遗漏；250排除项正式集读入0；已知同帧左右目不跨训练/留出侧；留出核心和缓冲无Train回流；所有正式集之间文件及像素精确重复0。旧74高优先级关联按新来源全部重映射，没有跨正式侧；已记录连续动作链也完整留出，未解决候选已退出Test。检索和有限看图不能排除尚未记录的全部重复动作。','',
  '实际构造Ultralytics '+v['ultralytics_version']+'的YOLODataset，三个集合逐label扫描且各读一个2张批次，随后从本版本新cache再加载核对。缓存只写新版本labels目录，源目录无新cache。每集找到数量、有效label数和框数与manifest一致。未实例化检测模型、未训练、未计算预测指标。','',
  '权重曝光：所有已有.pt的完整训练成员历史未能核实，标unknown；checkpoint日期和类别元信息不能替代训练图片清单。旧权重若训练过本次核心或缓冲，复制图片不使其变成未见Test。正式比较需从未见这些图片的初始化重训；train_from_scratch.example.yaml提供仅架构随机初始化示例，未执行训练。','',
  '后续新采集的独立场次测试使用future_independent_session_test单独来源/清单和评估子集，分别报告；本版不能替代它。','',
  '## 使用、复现与回滚','',
  '- 新数据入口：[dataset.yaml](./dataset.yaml)，Train/Val/Test清单在lists/，每行指向本版本独立副本。','- [自包含复核页](./review.html)可以单独复制并离线打开，内嵌数据、JS、样式、测试预览、片段与对照图。','- 全量分配：[manifest.csv](./manifest.csv)、[manifest.json](./manifest.json)；五类全部8148张，保留原路径/split、来源、场次/片段、帧时刻、目别、哈希、原因。','- 核验：[verification.json](./verification.json)；统计：[statistics.json](./statistics.json)、[split_distribution.csv](./split_distribution.csv)。','- 疑点按2组列在analysis/uncertain_groups.json；框与场景不待重标。','- 复现及回滚详见[REPRODUCE.md](./REPRODUCE.md)。原数据/配置未动，回滚无需搬回或删除任何图片。','']
 if (ROOT/'runtime/browser-validation.json').exists():
  lines += ['## 交付页核验','',
   'HTML约17.3MB，597张JPEG预览均已内嵌并逐项解码验证；内联JavaScript语法检查通过。已将同一HTML单独复制到只有一个文件的目录，通过本机HTTP实际验证50张翻页、场景/片段筛选、搜索、放大、49对风险图与两组复核入口，浏览器脚本错误0。静态检查无外部脚本、CSS或图片依赖。',
   '自动化浏览器只允许HTTP/HTTPS，因此没有直接执行file://协议打开测试；未绕过该限制。离线自包含性以全部资源内嵌检查及单文件隔离目录渲染核验。证据见runtime/html-static-validation.json、runtime/browser-validation.json和evidence/review-ui.png。','']
 (ROOT/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
 reproduce='''# 复现与回滚

本版本独立复制8148对图片和label，旧datasets/、旧split、metadata和250项隔离样本均未改。dataset.yaml只读取新版本三个正式清单；reserved/保存buffer及heldout_unused，不进入训练配置。

## 直接使用

把训练/验证程序的data指向本目录dataset.yaml。Train4346、Val1223、Test464。Test是same_session_segment_holdout_v1；未来独立采集单独命名future_independent_session_test并分别评估。

仅做配置预检（不会训练）：

```bash
/opt/VisionStudio/runtime/bin/python -B /home/misaka/workspace/script/model-training/train.py --config /home/misaka/workspace/dataset_versions/football_holdout_20261019_v1/train_from_scratch.example.yaml --dry-run
```

示例从已保存架构随机初始化，pretrained:false，不把曝光史未知的original_best.pt当成未见Test权重。正式训练仍需采用未用过留出图片的初始化；本轮没有启动训练。

## 重建相同分配

不在已发布目录运行选择/复制脚本。先创建新的空版本目录，在新目录复制本版本scripts/、analysis/、evidence/及SOURCE_FACTS.json，创建lists/与runtime/子目录；不要复制MATERIALIZED.json、COMPLETED.json或labels/*.cache。然后运行新目录中的：

```text
scripts/materialize.py
scripts/validate_view.py
scripts/build_deliverables.py
```

使用/opt/VisionStudio/runtime/bin/python -B执行。common.py按自身位置推导新ROOT，源DATA和旧审计路径为本机绝对路径。materialize读取冻结allocation/curator_completion和源SHA，核对源照片与label后复制，拒绝覆盖已完成版本。它重现已冻结人工决策，不宣称自动重现视觉判断。源文件不再匹配SHA时会停止；不要绕过检查。

重新分析时可从prepare→draft_segments→select_candidates→screen_pairs开始，但必须写新目录。原图/label、metadata、已有embedding与来源清单的SHA、随机种子、阈值及每次边界修订都在分析资料中。重用旧观察前须匹配同一照片对及SHA，不能只按变化的N/F/Q编号关联。SOURCE_FACTS.json记录本轮用户确认事实，优先于旧审计对场次的猜测。

## 独立验证与缓存

validate_view.py全量比较8398对源文件（包括旧250排除）及8148对新副本，检查名单、像素/文件哈希、同帧侧别、完整片段/缓冲、Val锁定及旧关联；真正构造YOLODataset和读取批次。首次创建本版本cache，第二次读本版本cache核对。源码数据不建cache，不实例化模型。

缓存只在本版本labels/，不会改变原始label。若今后有人工改标，必须另建数据版本并重做校验；不要把本报告套用于已改动的文件。

## 回滚

把训练配置的data恢复为/home/misaka/workspace/datasets/dataset.yaml，即恢复此前Train6925/Val1223/Test0的来源划分。新版本可以保留供追溯，无须删除或移动原图。回滚数据视图不能撤销权重曾看过Test的训练曝光。切换后核对加载日志和配置路径，避免误用其他版本缓存/实验结果。

## 单文件HTML

review.html所有必要资源均内嵌；可单独复制到任意位置直接打开，不需要HTTP服务器、旁边的JS目录或图片文件。预览是缩略图及对照页，原始像素仍在本版本图片目录；本机复核选择只保存在浏览器，不回写manifest或label。
'''
 (ROOT/'REPRODUCE.md').write_text(reproduce,encoding='utf-8')
 save(ROOT/'analysis/html_build.json',dict(html=str(ROOT/'review.html'),bytes=(ROOT/'review.html').stat().st_size,
  embedded_assets=len(assets),test_cards=len(tests),segment_cards=len(segments),pair_cards=len(pairs),uncertain_groups=2,
  external_javascript=0,external_css=0,external_images=0,relative_media_dependencies=0))
 print(json.dumps(load(ROOT/'analysis/html_build.json'),ensure_ascii=False))

if __name__=='__main__':main()
