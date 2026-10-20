"""Offline, paginated audit evidence browser. Never edits source data."""
import json
from pathlib import Path
from PIL import Image,ImageOps

ROOT=Path(__file__).resolve().parents[1]
pairs=json.loads((ROOT/'data/similarity-pairs.json').read_text())
rows=json.loads((ROOT/'data/inventory.json').read_text())
thumbs=ROOT/'review/thumbs';thumbs.mkdir(parents=True,exist_ok=True)
def actual(row):
    p=Path(row['image_path'])
    return p if p.is_file() else Path('/home/misaka/workspace/datasets/excluded/images')/row['split']/row['filename']
def actual_label(row):
    p=Path(row['label_path'])
    if p.is_file(): return p
    assert row['meta']['annotation_status']=='reviewed_excluded'
    p=Path('/home/misaka/workspace/datasets/excluded/labels')/row['split']/(Path(row['filename']).stem+'.txt')
    assert p.is_file(),p
    return p
indices=sorted({r[k] for r in pairs for k in ('index_a','index_b')})
for n,i in enumerate(indices):
    path=thumbs/f'{i:05d}.jpg'
    if not path.exists():
        with Image.open(actual(rows[i])) as im:
            im=ImageOps.contain(im.convert('RGB'),(320,180),Image.Resampling.BILINEAR)
            canvas=Image.new('RGB',(320,180),'#111827');canvas.paste(im,((320-im.width)//2,(180-im.height)//2))
            canvas.save(path,quality=78,optimize=False)
    if n%2000==0:print('thumbnails',n,len(indices),flush=True)
observations={}
for name in ('legacy-pair-visual-review.json','medium-pair-visual-review.json','root-temporal-visual-review.json'):
    p=ROOT/'data'/name
    if p.exists():
        data=json.loads(p.read_text())
        if isinstance(data,dict):data=data.get('records',[])
        for r in data:observations[r['pair_id']]=r
compact=[]
for r in pairs:
    item={k:r[k] for k in ('pair_id','split_a','split_b','phash_distance','dhash_distance','ssim','ssim_resolution','ssim_aligned','cosine_similarity','risk_level','delta_frames','delta_seconds','same_recording','assessment_status','recommended_review_reason','scene_disagreement','box_count_a','box_count_b','both_usable')}
    item['observation']=observations.get(r['pair_id'],{})
    item['evidence_page']='review/pair-pages/'+r['pair_id']+'.png' if (ROOT/'review/pair-pages'/f"{r['pair_id']}.png").is_file() else ''
    for eye in ('a','b'):
        row=rows[r['index_'+eye]]
        item[eye]=dict(filename=row['filename'],path=r['image_'+eye],uri=Path(r['image_'+eye]).as_uri(),split=r['split_'+eye],
                       recording=r['recording_id_'+eye],session=r['session_'+eye],frame=r['frame_'+eye],eye=r['eye_'+eye],
                       usable=row['usable'],flags=[k for k in ('Small','Occluded','Blurred','No Ball') if row['meta'][k]=='1'],
                       thumbnail=f"review/thumbs/{row['index']:05d}.jpg",label_path=str(actual_label(row)))
    compact.append(item)
data='window.AUDIT_PAIRS='+json.dumps(compact,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')+';\n'
(ROOT/'review/pairs-data.js').write_text(data)
samples=json.loads((ROOT/'data/visual-findings.json').read_text())
sample_pages=sorted({str(Path(r['page']).relative_to(ROOT)) for r in samples['records']})
sample_html=''.join(f'<a href="{p}" target="_blank">抽检页 {n+1:02d}</a>' for n,p in enumerate(sample_pages))
html='''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>足球数据集科研审计 · 相似图片复核</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f3f5f7;color:#16202c;font:15px/1.55 system-ui,sans-serif}header,main{max-width:1300px;margin:auto;padding:20px}header{background:#fff;border-bottom:1px solid #dce1e7}h1{font-size:26px;margin:0 0 8px}p{margin:8px 0}.warning{background:#fff5df;border-left:4px solid #c68b1d;padding:12px}.toolbar{display:flex;gap:10px;flex-wrap:wrap;position:sticky;top:0;z-index:5;background:#f3f5f7;padding:12px 0;border-bottom:1px solid #dce1e7}select,input,button{font:inherit;border:1px solid #aeb8c5;border-radius:5px;padding:7px;background:#fff}input[type=search]{min-width:260px;flex:1}button{cursor:pointer}button:disabled{opacity:.4;cursor:default}.count{padding:12px 0;color:#48576b}.pair{border:1px solid #ccd4de;border-radius:8px;background:white;margin:18px 0;overflow:hidden}.pairhead{padding:12px 16px;background:#edf1f6;display:flex;gap:12px;align-items:center;flex-wrap:wrap}.risk{border-radius:4px;padding:3px 9px;font-weight:600}.high{background:#ffe1da;color:#9e321d}.medium{background:#fff1c9;color:#775300}.low{background:#e4edf8;color:#285176}.critical{background:#8f1d1d;color:white}.images{display:grid;grid-template-columns:1fr 1fr;gap:18px;padding:16px}.images img{display:block;width:100%;max-height:320px;object-fit:contain;background:#111827}.path{font:12px/1.5 ui-monospace,monospace;overflow-wrap:anywhere;color:#526073}.filename{font-weight:600;overflow-wrap:anywhere}.metrics{display:flex;gap:18px;flex-wrap:wrap;padding:0 16px 12px}.details{padding:0 16px 16px}.flags{color:#975a00}.notes{background:#f1f6fb;border-radius:4px;padding:10px;margin:10px 0}.pager{display:flex;gap:12px;align-items:center;margin:14px 0}.samples{display:flex;flex-wrap:wrap;gap:12px}a{color:#175aa4}.split{font-weight:600}small{color:#59677a}footer{padding:20px 0;color:#526073}label{display:inline-flex;gap:6px;align-items:center}@media(max-width:740px){.images{grid-template-columns:1fr}header,main{padding:12px}h1{font-size:22px}.toolbar{position:static}}
</style></head><body><header><h1>足球数据集科研审计 · 相似图片复核</h1>
<p>8,398张完整审核记录；8,148张可用。候选为跨集合检索结果，不等于全部是重复或泄漏。默认展示74对高风险候选（含人工观察升级的16对）。</p>
<div class="warning"><b>隔离已完成：</b>250张排除图片及label已按用户授权移至 datasets/excluded/。图片字节、标注内容、metadata和分集字段保持；未自动修正其余候选或重新划分。<br>32对高风险来自已确认录像的≤1秒时序相邻；另42对来自旧导入数据的视觉近重复筛查，其中37对人工观察支持视觉近重复、5对仍不确定，真实采集场次均未知。</div>
<p><a href="AUDIT_REPORT.md">完整审计报告</a>　<a href="cross_split_duplicates.csv">全部候选CSV</a>　<a href="annotation_issues.csv">标注风险清单</a>　<a href="proposed_split_plan.md">两套划分建议</a></p></header>
<main><div class="toolbar"><select id="risk" aria-label="风险"><option value="high">高风险</option><option value="critical">严重</option><option value="medium">中风险</option><option value="low">低风险</option><option value="all">全部风险</option></select><select id="split" aria-label="集合对"><option value="all">全部集合对</option><option value="train-val">Train ↔ Val</option><option value="train-test">Train ↔ Test</option><option value="val-test">Val ↔ Test</option></select><input id="search" type="search" placeholder="搜索文件名、录像ID、pair编号"><label><input id="diff" type="checkbox">仅场景或框数不同</label><label><input id="seen" type="checkbox">仅已有助手视觉观察</label></div>
<div id="count" class="count"></div><div class="pager"><button id="prev">上一页</button><span id="page"></span><button id="next">下一页</button><button id="download">导出本机复核记录</button></div><div id="cards"></div><div class="pager"><button id="prev2">上一页</button><button id="next2">下一页</button></div>
<details><summary>64张分层随机标注抽检（32页，原图叠框）</summary><p>固定种子20261019；分层配额抽样，不能用候选比例估计全库错误率。每页含两张图与原有label。用户复核结果初始留空，助手观察另列。</p><div class="samples">SAMPLE_LINKS</div><p><a href="data/visual_sample_manifest.csv">抽样清单</a></p></details>
<details><summary>指标与限制</summary><p>pHash/dHash为64位Hamming距离。SSIM使用固定灰度尺寸，无自动大范围几何配准；原始和诊断平移对齐值分列。Embedding为ImageNet预训练MobileNetV3-small的576维L2向量，不是DINOv2。空白指标表示未执行或不适用，例如排除图片未提取embedding。录像ID不等于独立拍摄场次；缺少真实session时明确显示未知。</p><p>点击缩略图打开原始分辨率图片；“标注对照页”仅对选中74个证据对提供。以下选择仅存于当前浏览器本机并可导出，不会更改原label、metadata或CSV。</p></details><footer>科研审计证据；仅隔离250项为用户授权执行，其余修复和重分集尚未执行。</footer></main>
<script src="review/pairs-data.js"></script><script src="review/review-ui.js"></script></body></html>'''
(ROOT/'leakage_review.html').write_text(html.replace('SAMPLE_LINKS',sample_html))
js=r'''
const all=window.AUDIT_PAIRS; const $=id=>document.getElementById(id); let page=0,filtered=[],results={}; const size=20;
try {results=JSON.parse(localStorage.getItem('football-audit-20261019')||'{}')} catch(e){}
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=v=>v==null?'未执行 / 不适用':Number(v).toFixed(4);
const labels={'Small':'小目标','Occluded':'遮挡','Blurred':'运动模糊','No Ball':'无球'};
function filter(){const query=$('search').value.toLowerCase();filtered=all.filter(r=>($('risk').value==='all'||r.risk_level===$('risk').value)&&($('split').value==='all'||[r.split_a,r.split_b].sort().join('-')===$('split').value.split('-').sort().join('-'))&&(!$('diff').checked||r.scene_disagreement.length||r.box_count_a!==r.box_count_b)&&(!$('seen').checked||Object.keys(r.observation).length)&&(!query||JSON.stringify([r.pair_id,r.a.filename,r.b.filename,r.a.recording,r.b.recording]).toLowerCase().includes(query)));page=0;render();}
function side(r){return `<div><a href="${esc(r.uri)}" target="_blank"><img loading="lazy" src="${esc(r.thumbnail)}" alt="${esc(r.filename)}"></a><p class="filename"><span class="split">${esc(r.split)}</span> · ${esc(r.filename)}</p><p class="flags">${r.flags.map(x=>labels[x]).join(' · ')}</p><small>${r.usable?'可用':'已隔离，不训练'}；录像：${esc(r.recording||'未知')}<br>真实拍摄场次：${esc(r.session||'未知')}；帧：${esc(r.frame??'未知')}；目别：${esc(r.eye||'未知')}</small><p class="path">${esc(r.path)}</p></div>`}
function render(){const pages=Math.max(1,Math.ceil(filtered.length/size));page=Math.min(page,pages-1);$('count').textContent=`检索候选共 ${all.length.toLocaleString()} 对；当前筛选 ${filtered.length.toLocaleString()} 对。每页20对，图片按需加载。`;$('page').textContent=`第 ${page+1} / ${pages} 页`;
for(const id of ['prev','prev2'])$(id).disabled=page===0;for(const id of ['next','next2'])$(id).disabled=(page+1)*size>=filtered.length;
$('cards').innerHTML=filtered.slice(page*size,(page+1)*size).map(r=>{const ob=r.observation||{};const note=ob.assistant_observation||ob.reason||ob.visual_assessment||'';return `<article class="pair" data-id="${r.pair_id}"><div class="pairhead"><b>${r.pair_id}</b><span class="risk ${r.risk_level}">${({high:'高风险',medium:'中风险',low:'低风险',critical:'严重'})[r.risk_level]}</span><span>${esc(r.split_a)} ↔ ${esc(r.split_b)}</span><span>${r.both_usable?'双方均可用':'含归档参考'}</span></div><div class="images">${side(r.a)}${side(r.b)}</div><div class="metrics"><span>pHash：${r.phash_distance}</span><span>dHash：${r.dhash_distance}</span><span>SSIM：${fmt(r.ssim)}（${r.ssim_resolution}）</span><span>诊断对齐SSIM：${fmt(r.ssim_aligned)}</span><span>cosine：${fmt(r.cosine_similarity)}</span></div><div class="details"><p>${esc(r.recommended_review_reason)}</p><p>${r.same_recording?`同录像；间隔 ${r.delta_frames} 帧${r.delta_seconds==null?'':` / ${r.delta_seconds.toFixed(3)} 秒`}`:'未确认来自同一录像/采集事件'}</p><p>框数：${r.box_count_a} / ${r.box_count_b}；场景差异：${esc(r.scene_disagreement.map(x=>labels[x]).join('、')||'无')}</p>${note?`<div class="notes">助手观察（非用户结论）：${esc(note)}</div>`:''}${r.evidence_page?`<a href="${r.evidence_page}" target="_blank">原尺寸标注对照页</a>`:''}<p><label>用户复核结果：<select class="review" data-pair="${r.pair_id}"><option value="">待复核（留空）</option><option value="visual_near_duplicate">确认视觉近重复</option><option value="same_background_only">仅共同背景</option><option value="event_leakage_confirmed">有采集证据确认泄漏</option><option value="not_duplicate">不是重复</option><option value="uncertain">仍不确定</option></select></label></p></div></article>`}).join('');
document.querySelectorAll('.review').forEach(s=>{s.value=results[s.dataset.pair]||'';s.onchange=()=>{results[s.dataset.pair]=s.value;try{localStorage.setItem('football-audit-20261019',JSON.stringify(results))}catch(e){}}});}
for(const id of ['risk','split','diff','seen'])$(id).onchange=filter;$('search').oninput=filter;
for(const id of ['prev','prev2'])$(id).onclick=()=>{page--;render();window.scrollTo({top:0,behavior:'smooth'})};for(const id of ['next','next2'])$(id).onclick=()=>{page++;render();window.scrollTo({top:0,behavior:'smooth'})};
$('download').onclick=()=>{let csv='pair_id,review_status\r\n';for(const [id,value]of Object.entries(results))if(value)csv+=id+','+value+'\r\n';const url=URL.createObjectURL(new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='audit-human-reviews.csv';a.click();URL.revokeObjectURL(url)};filter();
'''
(ROOT/'review/review-ui.js').write_text(js)
(ROOT/'data/html-build.json').write_text(json.dumps(dict(pairs=len(compact),thumbnails=len(indices),sample_pages=len(sample_pages),offline=True,user_results_initially_blank=True,source_modified=False),indent=2)+'\n')
print(json.dumps(dict(html=str(ROOT/'leakage_review.html'),pairs=len(compact),thumbnails=len(indices))))
