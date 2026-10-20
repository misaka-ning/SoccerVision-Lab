"""Combine audit findings, preserving all original annotations and partitions."""
import csv,hashlib,json,os,platform,sys
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
os.environ['MPLCONFIGDIR']=str(ROOT/'logs/matplotlib-config')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

def load(name):return json.loads((ROOT/name).read_text())
def save(name,x):(ROOT/name).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def read_csv(name):
    with (ROOT/name).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
rows=load('data/inventory.json');lookup={r['filename']:r for r in rows}
pairs=load('data/similarity-pairs.json');triage=load('data/final-triage-summary.json')
summary=load('data/inventory-summary.json');provenance=load('data/provenance.json')
power=load('data/statistical_power.json');visual=load('data/visual-findings.json')
baseline=read_csv('annotation_issues_base.csv')
def actual(path,kind,row):
    p=Path(path)
    return str(p if p.is_file() else Path('/home/misaka/workspace/datasets/excluded')/kind/row['split']/p.name)

# Post-isolation excluded audit: keep baseline values explicitly as history.
excluded=read_csv('excluded_samples_audit.csv')
if not (ROOT/'data/excluded_samples_audit_pre_isolation.csv').exists():
    (ROOT/'data/excluded_samples_audit_pre_isolation.csv').write_bytes((ROOT/'excluded_samples_audit.csv').read_bytes())
for r in excluded:
    r.setdefault('original_image_path',r['image_path']);r.setdefault('original_label_path',r['label_path'])
    r['image_path']=actual(r['original_image_path'],'images',r);r['label_path']=actual(r['original_label_path'],'labels',r)
    r['was_in_original_training_path']='true';r['raw_directory_scanned_by_yaml']='false'
    r['training_filter_verified']='post_isolation_actual_loader_discovery_absent'
    row=lookup[Path(r['original_image_path']).name]
    r['image_sha256']=row['image_sha256'];r['label_sha256']=row['label_sha256']
    r['isolation_manifest']='/home/misaka/workspace/datasets/excluded/manifest.json'
    r['review_result']=''
with (ROOT/'excluded_samples_audit.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(excluded[0]));w.writeheader();w.writerows(excluded)

# The old auto/preserved counts are provenance, not current errors.
issue_types=Counter(r['issue_type'] for r in baseline)
keep=[]
for r in baseline:
    if r['severity']=='info' or 'raw_training' in r['issue_type'] or 'training_path' in r['issue_type']:continue
    row=lookup[Path(r['image_path']).name]
    r=dict(r,original_image_path=r['image_path'],image_path=actual(r['image_path'],'images',row),
           label_path=actual(r['label_path'],'labels',row),phase='current_after_isolation',
           issue_basis='automatic_risk_screen_not_groundtruth')
    if row['meta']['annotation_status']=='reviewed_excluded':r['severity']='archived_error_not_loaded'
    keep.append(r)
for r in visual['records']:
    if not r['requires_review']:continue
    keep.append(dict(image_path=r['source_current_image_path'],label_path=r['source_current_label_path'],
        original_image_path=r['path'],split=r['split'],status=r['annotation_status'],issue_type='stratified_visual_review_candidate',
        severity=r['severity'],evidence=r['page']+'; '+r['assistant_observation'],recommendation=r['issue'] or '按原图逐项复核；不自动改标',
        requires_review='true',review_result='',phase='current_after_isolation',issue_basis='assistant_actual_visual_observation'))
legacy=load('data/legacy-pair-visual-review.json')
seen=set()
for pair in legacy:
    for r in pair.get('annotation_candidates',[]):
        key=(r['filename'],r['issue_type'])
        if key in seen:continue
        seen.add(key);row=lookup[r['filename']]
        keep.append(dict(image_path=actual(r['image_path'],'images',row),label_path=actual(r['label_path'],'labels',row),
            original_image_path=r['image_path'],split=row['split'],status=row['meta']['annotation_status'],
            issue_type=r['issue_type'],severity='candidate',evidence=pair['pair_id']+'; '+r['assistant_observation'],
            recommendation=r['reason'],requires_review='true',review_result='',phase='current_after_isolation',
            issue_basis='assistant_actual_visual_observation; historical_policy_may_differ'))
for r in pairs:
    if r['risk_level']!='high' or r['same_recording']:continue
    if not r['scene_disagreement'] and r['box_count_a']==r['box_count_b']:continue
    row=rows[r['index_a']]
    keep.append(dict(image_path=r['image_a'],label_path=actual(row['label_path'],'labels',row),
        original_image_path=row['image_path'],split=row['split'],status=row['meta']['annotation_status'],
        issue_type='visually_similar_pair_annotation_disagreement',severity='candidate',
        evidence=f"{r['pair_id']}; paired={r['image_b']}; flags={','.join(r['scene_disagreement'])}; boxes={r['box_count_a']}/{r['box_count_b']}",
        recommendation='逐图确认球是否可见、遮挡和运动是否不同；相似图片标签不同不自动构成错误',
        requires_review='true',review_result='',phase='current_after_isolation',issue_basis='paired_visual_candidate_not_error_adjudication'))
cols=['issue_id','image_path','label_path','original_image_path','split','status','issue_type','severity','evidence','recommendation','requires_review','review_result','phase','issue_basis']
for n,r in enumerate(keep):r['issue_id']=f'A{n+1:05d}';r['review_result']=''
with (ROOT/'annotation_issues.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore');w.writeheader();w.writerows(keep)
save('data/annotation-issue-summary.json',dict(rows=len(keep),unique_images=len({r['image_path'] for r in keep}),
    counts=dict(Counter(r['issue_type'] for r in keep)),baseline_issue_types=dict(issue_types),
    warning='Risk-screen and purposive review rows are not confirmed errors or a population error-rate estimate. Historical count differences remain only in annotation_issues_base.csv.'))

# Reproducible scientific figures, with factual counts and no model results.
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10})
fig,ax=plt.subplots(1,2,figsize=(10,3.8))
splits=['train','val','test'];usable=[sum(r['usable'] and r['split']==s for r in rows) for s in splits]
ax[0].bar(splits,usable,color=['#3476a8','#2d937e','#b56b3c']);ax[0].set_yscale('log');ax[0].set_ylabel('Usable images (log scale)')
for i,n in enumerate(usable):ax[0].text(i,n*1.13,str(n),ha='center')
ax[0].set_ylim(50,15000);ax[0].set_title('Current split sizes')
labels=['Small positives','Occluded positives','Blurred positives','No-ball negatives'];counts=[14,26,30,48]
ax[1].barh(labels,counts,color='#3476a8');ax[1].set_xlim(0,57);ax[1].set_xlabel('Test image count (correlated samples)');ax[1].set_title('Test evaluation denominators')
for i,n in enumerate(counts):ax[1].text(n+1,i,str(n),va='center')
fig.tight_layout();fig.savefig(ROOT/'figures/split-and-test-counts.png',dpi=180);plt.close(fig)
fig,ax=plt.subplots(figsize=(7.8,4.2))
illustrative=power['illustrative_intervals'];keys=['Small_positive_images','Occluded_positive_images','Blurred_positive_images','negative_images']
for i,k in enumerate(keys):
    ci=illustrative[k]['all_correct_wilson95'];ax.plot([ci[0],ci[1]],[i,i],color='#3476a8',lw=3);ax.scatter([ci[0],ci[1]],[i,i],color='#3476a8')
ax.set_yticks(range(4),labels);ax.set_xlim(.65,1.015);ax.set_xlabel('Hypothetical all-success proportion: Wilson 95% interval');ax.set_title('Illustration only: independent trials assumed; no predictions run');ax.grid(axis='x',alpha=.2)
fig.tight_layout();fig.savefig(ROOT/'figures/illustrative-wilson.png',dpi=180);plt.close(fig)
fig,ax=plt.subplots(figsize=(7.8,4.4));rng=np.random.default_rng(20261019)
valid=[r for r in pairs if r['cosine_similarity'] is not None];sel=rng.choice(len(valid),min(4000,len(valid)),replace=False)
ax.scatter([valid[i]['ssim'] for i in sel],[valid[i]['cosine_similarity'] for i in sel],s=5,alpha=.2,c='#65809b',label='Candidate sample (seeded)')
for category,color,text in [('time','#bd5a37','Confirmed <=1s adjacency'),('visual','#276c9a','Visual review priority')]:
    q=[r for r in pairs if r['risk_level']=='high' and ((r['same_recording'])==(category=='time'))]
    ax.scatter([r['ssim'] for r in q],[r['cosine_similarity'] for r in q],s=20,c=color,label=text)
ax.set_xlabel('Raw SSIM (recorded per-pair resolution)');ax.set_ylabel('Pretrained cosine similarity');ax.set_title('Similarity signals are candidates, not event identity');ax.legend(fontsize=8);fig.tight_layout();fig.savefig(ROOT/'figures/similarity-signals.png',dpi=180);plt.close(fig)

started=load('data/start-state.json')['created_at_utc'];finished=datetime.now(timezone.utc).isoformat()
report=f'''# YOLO26s 足球数据集科研级审计报告

**最终结论：BLOCKED（正式科研E00/E01暂不建议开始）。** 250张排除样本已按用户追加授权完成物理隔离，当前训练入口已不再混入；阻断点仍在跨集合时序依赖、高风险视觉近重复及Test专项样本独立性。此结论不表示全部候选均已被确认为同一采集事件。

执行开始：{started}；报告生成：{finished}。时间为UTC（香港时间+8小时），2026-10-19。全量扫描、哈希、标签、来源和相似性检索均实际执行；没有运行目标检测模型预测、E00指标、E01训练、消融实验或TensorRT更新。

## 1. 版本、范围和用户后续授权

初始审计只读 `/home/misaka/workspace/datasets/`，读取8398条metadata、8398张图片和8398份label；实际全像素解码全部通过。冻结版本metadata SHA256为 `cb2386ef97c2f864cad27adf8fc06dc6fc74cea2caf828f32a685abc05985ef9`，YAML SHA256为 `7781d543cc43364f2a2598ff596adb05a8e80b4547af40195665565a8eef05b6`。

审计进行中，用户明确追加授权：“可以帮我把那250张图片和label放到和images、labels同级的另外的文件夹中，隔离开来”。只执行该窄范围操作：将250图片和250label按原split移至 `datasets/excluded/images|labels/train|val|test/`。500份备份、逐项原/新路径与SHA、日志和回滚规则位于 [isolation](./isolation/REPORT.md)；[独立核验PASS](./isolation/verification.json)。全部8398图与8398label映射后SHA保持。未修改图片内容、label内容、metadata、YAML或任何split字段；其余候选和重分集方案未执行。

根metadata仍是8398张完整审核记录；250排除图片实际路径由 `datasets/excluded/manifest.json` 解析，归档metadata副本只含对应250条原记录。不能把这250条旧路径的缺席报告为新丢图。当前活动目录是8148张/8148label，另有归档250张/250label。

环境使用现有 /opt/VisionStudio/runtime：Python3.10、PyTorch2.9.1+cpu、torchvision0.24.1+cpu、Ultralytics8.4.173、OpenCV4.11.0、NumPy/Pillow/Matplotlib（精确版本见manifest）。每个计算进程单线程、nice10；未安装新依赖。仅下载PyTorch官方9.8MB ImageNet权重到本审计models目录，SHA与来源已记录。未改生产环境。

## 2. 最严重的五项现存风险

| 优先级 | 风险 | 事实与限制 | 建议 |
| --- | --- | --- | --- |
| P0 | 同一采集片段跨训练/评估 | SHA恢复来源后，Train/Test最短4帧=0.267秒；Train/Val最短6帧=0.4秒。≤1秒共32图像对、8个不同时间对；不是32个独立泄漏事件 | 先按拍摄/时序组复核，设计缓冲或场次留出；不能只靠图像哈希 |
| P0 | 旧数据视觉近重复跨集合 | 最终42对视觉优先复核候选，37对实际视觉观察支持近重复、5对仍不确定；714张legacy真实录像/session未知，不能确认事件身份 | 审核原始来源及候选，冻结决策后再统一划分 |
| P0 | Test专项分母小且高度相关 | 127 Test中79有球/48无球；Small14正图仅7立体时刻且跨3秒，Occluded26正图仅14时刻且跨7.27秒 | 采用独立采集事件/session扩充测试；不要把左右目或相邻帧当独立试验 |
| P1 | 场景标签存在口径/主观性风险 | 自动Small候选58、近边Occluded候选199；64张实际分层抽检中18张可用图建议复核，另8张为排除代表；这不是全库错误率 | 统一边缘截断、完整球尺度和运动模糊规范，复核候选而非自动改标 |
| P1 | 来源与评测协议不完整 | 7684张关联3录像，但3录像不等于3独立session；714张legacy真实来源未知；80类参考权重的E00映射尚未执行验证 | 建立采集session清单，明确E00 sports ball32→football0协议及E01单类头 |

原先“250排除样本会被直接读取”的P0风险已修复，不再列作当前未解决阻断。4份越界label也随排除集隔离，当前活动目录无该异常。

## 3. A：文件完整性与实际数据

| 集合 | 完整审核记录 | 活动可用 | 已隔离 | 有球 | 无球 | 可用框 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Train | 8100 | 7857 | 243 | 4997 | 2860 | 5194 |
| Val | 170 | 164 | 6 | 144 | 20 | 144 |
| Test | 128 | 127 | 1 | 79 | 48 | 79 |
| 合计 | 8398 | 8148 | 250 | 5220 | 2928 | 5417 |

197张可用图含两个球。独立复核与既有统计一致；**来源独立性结论有实质补充**：先前只覆盖6508条完整metadata，本次依据历史清单SHA额外恢复1176张，发现跨split近时序关联。

无孤立图片/label、重复metadata键、重复inode、软链、异常扩展名、坏图、近全黑/白/空白候选。分辨率672×376有7869张、1280×720有528张、1920×1080有1张；PNG7684/JPEG714。极小框及高IoU同图疑似重复框未触发本次记录阈值；这些是自动筛查覆盖，不证明不存在视觉漏标。

全部图片和label SHA及路径见 [inventory](./data/inventory.json)、[物理清单](./data/physical-inventory.json)。隔离后按manifest重新映射并独立逐SHA核验，未丢失文件。

## 4. B：精确/感知/深度/结构相似性

### 精确重复

全8398张计算文件SHA256和“RGB解码尺寸+像素字节”SHA256。三种跨集合组合均为 **0个文件精确重复组、0个解码像素精确重复组**。pHash相同不代表像素完全相同。

### 近重复方法与覆盖

- pHash64：32×32灰图DCT低频8×8，排除DC取median后比较；dHash64：9×8灰图横向差分。算法位序与resize版本见scripts和inventory-summary。分别用BK树做半径16精确索引查询；候选保留pHash≤12或dHash≤10。没有全8398×8398多重暴力匹配。
- B3已执行替代预训练模型：torchvision MobileNetV3-small / ImageNet1K V1，全部8148可用图提取576维末层全局均值特征并L2归一。RGB全图缩放224×224、ImageNet均值方差、无center crop（保留画边信息，偏离官方分类预处理）。CPU单线程，eval/inference_mode，未微调。DINOv2、FAISS未安装/未执行；采用已具备依赖的替代骨干及分块精确内积近邻，范围仅跨集合。详细模型权重SHA、版本和限制在 [embedding-model](./data/embedding-model.json)。[官方模型说明](https://docs.pytorch.org/vision/stable/models/generated/torchvision.models.mobilenet_v3_small.html)。
- 对每个held-out图检索另一split top5，并保留反向top1，记录全跨split cosine分位数及多个阈值数量。分类预训练全局特征不保证足球级语义或事件身份，不能单独判泄漏。
- 对联合候选计算Gaussian11/σ1.5 SSIM，数据范围255，固定灰度128×72、无crop全图缩放；按该尺度初判的61对高风险进一步256×144精化，重算后58对仍为自动高风险。对这58对尝试phase correlation，26对满足response≥0.3且平移向量长度≤8像素，计算诊断SSIM；未作全局或大范围配准。**不同分辨率和raw/aligned值分列；低SSIM不作为否决相似采集的依据。**
- BK查询与全枚举的独立数值对照、SSIM身份/对称/常量及float64参考检查通过，见 [方法验证](./logs/similarity-method-independent-check.json)。

联合检索22391对是**候选池**，不是22391次泄漏。自动高58对；对16个中风险目的性样本实际查看后提高复核优先级，最终高74、中7556、低14761；保留原自动等级与人工观察，用户review_status全部初始为空。

| 集合对 | 最终高优先级 | 其中≤1秒时序 | 视觉优先复核 | 精确重复 |
| --- | ---: | ---: | ---: | ---: |
| Train / Val | 37 | 12 | 25 | 0 |
| Train / Test | 32 | 20 | 12 | 0 |
| Val / Test | 5 | 0 | 5 | 0 |
| 合计 | 74 | 32 | 42 | 0 |

42对视觉候选中，37对在实际对照页显示主体球纹/手部姿态/物件布局高度重合；5对主体变化仍不能确认。**视觉相似被支持，不等于已确认同一session、同一录像、相邻帧或科研事件泄漏。**32个时间相邻图像对则有SHA恢复的录像来源证据；root实际看了8个独立时间对的代表页，观察与连续采集一致，但其中取景差异较大者不是“视觉副本”。

[全部候选CSV](./cross_split_duplicates.csv)含方法、路径、真正session空值、录像ID、帧号、Hamming/SSIM/cosine、风险及复核字段；未执行指标留空。排除图片未提取embedding，因此其cosine为空。[HTML复核页面](./leakage_review.html)可离线打开、按风险/集合/搜索过滤、分页、查看原图和标注证据，仅在浏览器本机记录用户判断。

哈希阈值敏感性（全部图片的累计候选对，均非真值）：

| 集合对 | p≤0 | p≤4 | p≤8 | p≤12 | p≤16 | d≤4 | d≤8 | d≤12 | d≤16 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Train/Val | 4 | 23 | 88 | 270 | 934 | 74 | 330 | 1047 | 5078 |
| Train/Test | 1 | 12 | 40 | 78 | 342 | 23 | 78 | 341 | 2215 |
| Val/Test | 0 | 0 | 1 | 13 | 29 | 0 | 11 | 25 | 124 |

更多2/6/10阈值、可用子集及cosine完整分布见 [similarity-summary](./data/similarity-summary.json)；[最终人工优先级](./data/final-triage-summary.json)单独保存。初版严格SSIM门槛的阶段结果保留在initial-strict-ssim文件，最终方法遵循用户要求不以单一SSIM否决位移相似，且不为获得PASS调整数据。

## 5. C：时间、双目与采集来源

原6508张完整metadata外，1176张plain frame通过旧restructured-manifest中的png_sha256逐一与当前字节匹配，恢复104748录像、frame、eye及15FPS。7684张最终关联3个录像文件；714张legacy只确认旧导入文件映射，无法确认原始录像/帧号/真实拍摄场次。3个录像均有日期信息，但不能据日期相近就合并/分开为独立session。

- 同视频同帧跨split（包括左右目拆分）：**0组**，范围是可可靠恢复录像的7684张；不能对714张未知来源作同等保证。
- Train/Test最近4948→4952，4帧/0.267秒，例 [P000001](./review/pair-pages/P000001.png)。
- Train/Val最近2247→2253，6帧/0.4秒，例 [P000005](./review/pair-pages/P000005.png)。
- ≤1秒：Train/Test5个不同时间对/20个目别组合图像对；Train/Val3个时间对/12图像对。不能将两目组合计成4个独立泄漏事件。
- Val/Test已知录像最近2256帧/150.4秒；同录像本身是独立性风险，不直接等同像素/同一动作泄漏。

[temporal_pairs.csv](./data/temporal_pairs.csv)有4596行双向最近时间候选，包含更大间隔，不能把全部4596行称作泄漏；1/5/15/30/75/150帧敏感性、连续观测run及source证据路径/哈希见 [provenance.json](./data/provenance.json)。共同实验室背景单独不足以确认同一采集事件。

## 6. D：划分与科研统计可靠性

![分集与Test分母](./figures/split-and-test-counts.png)

| 场景 | Train可用图 | Val可用图 | Test可用图 | Test实际有球图/框 |
| --- | ---: | ---: | ---: | ---: |
| Small | 1581 | 32 | 14 | 14 / 14 |
| Occluded | 1350 | 40 | 26 | 26 / 26 |
| Blurred | 2166 | 68 | 44 | **30 / 30** |
| No Ball | 2860 | 20 | 48 | 0 / 0 |

场景是图级多标签而非实例级属性；多球图不能把该图所有框都自动归为小球/遮挡球。Test当前单球，故以上专项正例框数可确认。Blurred的44图中14为负样本，不进入足球Recall分母。全部组合分布、source录像分布、像素/672尺度与面积分档见 [split_distribution.csv](./split_distribution.csv)和 [statistical_power.json](./data/statistical_power.json)。Small按既有规范“完整球长边672尺度约40像素”，bbox残片不能当作完整球尺度。

**只有127张可用Test不足以支撑可靠的专项论文评价。** Small14图仅7个双目时刻，5119–5164跨3.0秒；Occluded26图14时刻，4976–5085跨7.27秒；Blurred30正图中14张来自7个时刻/18.67秒，其余16 legacy源事件未知。7个时刻也不保证7个独立事件，不能直接把相关图当Bernoulli独立试验。

![假设Wilson区间](./figures/illustrative-wilson.png)

以下只是**假设独立且全部命中**的二项Wilson95%演示，不是实际Recall、更不是AP/mAP置信区间：n=14下界78.47%；n=26下界87.13%；n=30下界88.65%。48张无球即使假设0误检，双侧Wilson的误检概率上界约7.41%，仍不能支持FPR≤1%的强结论。实际预测未运行，真实Recall/AP均不可用。Wilson方法见 [NIST](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm)。

结构对比、消融、微调和不同种子必须使用同一冻结数据版本、同一评估阈值与后处理，不能每实验重新抽图或按结果选择测试集。多个训练随机种子减少训练随机性，不能补偿测试集相关性、固定场景或数据泄漏。将来应报告事件/session层面的配对bootstrap/留组评估；当前session缺失，不能伪造聚类置信区间或有效样本数。

扩Test应以独立采集事件及场景覆盖为依据：最坏比例约±5个百分点的95%精度参考需385个独立试验/专项；无球若假设0FP且目标Wilson上界≤1%需381个独立负例。这不是385帧，也不是保证mAP精度的样本数。见计划内关联性/ICC敏感性。新增6个Test+2个Val采集场次是操作预算建议，不是经数据证明的独立性保证。

## 7. E：标注与场景抽检

所有可用5417框均为class0，格式有效、有限、正宽高，归一化xywh及xyxy边界通过本审计严格校验。4个真实越界均属于已隔离train排除样本：frame_001674_right、frame_003650_right、video_4bec9c343db72928_frame_00004643_left、video_4bec9c343db72928_frame_00007724_right。其各xywh分量本身在[0,1]，不能只检查分量忽略角点。

250排除中有效非空41、有效空205、无效4；6张NoBall=1而非空label也在该排除集内。它们的历史场景和参考标注保留，不纳入确认负例。可用子集NoBall与当前有效label数量无冲突；当前auto_box_count/preserved_box_count是历史计数，与最终人工框不同的5546条仅为追溯信息，不能宣称5546标注错误。

按seed20261019、普通清晰有球/Small/Occluded/Blurred/NoBall/多球/Small+Occluded/Small+Blurred/排除代表分层配额抽64张，覆盖train37/val16/test11；去重后实际逐页查看32张叠框页，所有初始review_result为空。26条建议复核含8个排除代表，18张为可用样本；抽样不是等概率总体错误率设计，不能用26/64估计全库错误率。近重复视觉对另实际看42页（26自动高+16目的性中风险），root另看8个独立时间对代表；方法与观察分别留证，不把助手观察填成用户审核通过。

较具体的可用风险案例：S005 frame_005240_right球尺度约32px但Small=0、S035 frame_004889_left约35px但Small=0；S026 legacy_test_000006下边截断但Occluded=0。它们仍是按原图规范复核的候选，前4批保留旧口径的历史政策可能解释一部分边缘差异，不能直接覆盖用户结果。Occluded/Blurred不靠简单亮度/梯度自动判真值。

自动Small58和近边Occluded199只作筛查，不是257个确定错误；完整候选含额外人工观察和成对标签差异，见 [annotation_issues.csv](./annotation_issues.csv)。同背景或图像相似时，球移出/被挡与运动程度变化都可使正确标签不同。每行包含路径、证据、风险、建议与空复核字段；[64图抽检清单](./data/visual_sample_manifest.csv)及 [原图叠框页](./samples/page-000.png)保留原label全文。没有覆盖任何标注。

## 8. F：训练入口安全和缓存

[实际安装源码与隔离验证](./data/safety-report.md)：当前Ultralytics8.4.173的get_img_files原先发现8100/170/128，250排除全被发现，205个空label会被识别为背景；4份越界label在审计目录物理副本上也被verify_image_label接受。该loader分量容差与本审计角点校验不同。上述是已留证的**隔离前状态**。

隔离后再次实际调用原入口发现7857/164/127，总8148，excluded0、active角点异常0。YAML仍正确指向原images/train|val|test；归档不在这三条路径下。未找到原数据.cache、图像软链或重复inode；本地该版cache hash含路径/size/mtime_ns，但并非内容SHA，不能据此保证标注版本。cache:false也不等于禁止label cache。审计只读检查原cache位置；运行时配置/cache均定向本审计safety，不在源数据建cache；临时发现视图也仅在审计目录，未开始模型训练。

本任务是单类别0=football，不是COCO32。80类参考预训练权重可在E01训练时由DetectionTrainer以data['nc']重建单类头；本审计只验证源码路径，不声称YOLO26s模型成功实例化或训练。**E00若直接评估原80类模型，需明确只取sports ball32并映射为数据类0的协议；不能把人类0当足球、也不能把所有80类直接single_cls混为足球。** 当前没有执行该评估，E00兼容性/真实性能留待协议确认。[Ultralytics数据格式](https://docs.ultralytics.com/datasets/detect/)要求零起始类别及归一化xywh，具体本机loader行为以已保存源码和验证为准。

## 9. 建议修复顺序与两套方案

详见 [proposed_split_plan.md](./proposed_split_plan.md)，所有候选处理均未执行，唯一已执行的是用户追加授权的250项隔离。

1. **P0先冻结科研协议与候选决策**：复核32时序图像对及42视觉候选，补来源；修复后再冻结E00/E01评估。表中的37视觉支持不是37个已确认同源事件。
2. **最小改动**：仅保留现有eval并处理风险边。最终74高优先级涉及49个train候选；单处理train仍遗留5条Val/Test风险边。保Test需另处理5张Val，预算train7808/val159/test127=8094；保Val可处理4张Test，预算7808/164/123=8095。这只是候选上界预算，未自动执行且仍共享录像，不能宣称成为独立科研测试。
3. **科研优先**：按真实采集session/录像/时间组留出，未知714 legacy先查来源或在主实验中隔离。现有3录像整留出的示例6212/69/1154（未知713可用legacy另行待定）虽扩大Test，却Val无Blurred覆盖且session独立性未知，不能直接采用。优先新增独立测试与验证场次，并满足正例/负例/专项事件数，再确定图数。
4. **P1标注复核**：统一完整球Small尺度、画边截断Occluded、方向性Blurred定义；复核候选，不把历史计数字段当当前真值。保留原标签版本以便消融可追溯。
5. 固定测试清单、数据版本SHA、随机种子、后处理、训练预算和置信区间方法；再开始E00基线与E01微调，所有网络变体共用同一数据版本。

## 10. 未执行、无法确认及结论边界

- 没有执行DINOv2/FAISS；B3实际使用已记录的预训练替代与精确内积检索，不能称DINO证据。
- 真实物理session数量和714 legacy时序无法可靠恢复；没有根据同背景/文件mtime强行推断。
- 人工视觉抽检不是全量8398重新画框，也没有人工确认全部22391候选；实际覆盖42视觉pair+8时间代表pair+64分层图有独立记录。
- 未全量计算旋转/透视/曝光不变的匹配或对齐；SSIM不同尺度与有限平移诊断均明确标注，无法证明绝对无泄漏。
- 未运行检测预测、真实Recall/AP/mAP、E00/E01、种子重复或消融；统计区间均为有条件演示，不能写成实测模型结果。
- 没有自动删除、重标、重分配任何其他图；250项物理隔离是审计开始后用户明确授权的唯一例外。

**最终：BLOCKED。** 当前数据可以做安全I/O/加载检查（已完成），但不建议直接开始用于论文结论的正式E00/E01。需先解决/裁决跨集合关联和独立测试设计，确认场景规范与E00类别协议，再进行冻结数据上的基线、微调和消融。PASS不能靠修改审计结论或忽略低SSIM候选获得。

## 11. 复现与输出索引

详见 [audit_manifest.json](./audit_manifest.json)的参数、版本、阈值、脚本SHA、源SHA、步骤覆盖、未执行理由和所有输出清单。相似性数值验证及源路径映射独立验证都有记录。脚本只写审计目录；isolate_excluded.py的500文件迁移必须有本轮已记录的明确授权，不应为了重跑审计再执行一次。

- [相似性HTML](./leakage_review.html)、[cross_split_duplicates.csv](./cross_split_duplicates.csv)。
- [split_distribution.csv](./split_distribution.csv)、[annotation_issues.csv](./annotation_issues.csv)、[excluded_samples_audit.csv](./excluded_samples_audit.csv)。
- [采集与时间证据](./data/provenance.json)、[原始来源SHA匹配](./data/provenance_summary.md)。
- [隔离计划/日志/备份/核验](./isolation/REPORT.md)、[训练入口前后验证](./safety/training-safety.json)。
'''
(ROOT/'AUDIT_REPORT.md').write_text(report)
save('data/report-build.json',dict(report='AUDIT_REPORT.md',conclusion='BLOCKED',annotation_issue_rows=len(keep),
    annotation_unique_images=len({r['image_path'] for r in keep}),excluded_rows=len(excluded),created_at_utc=finished,
    checks_executed=True,model_predictions_executed=False))
print(json.dumps(dict(report=str(ROOT/'AUDIT_REPORT.md'),annotation_rows=len(keep),annotation_unique_images=len({r['image_path'] for r in keep}),excluded_rows=len(excluded),figures=3,conclusion='BLOCKED'),ensure_ascii=False))
