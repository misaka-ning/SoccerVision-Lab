"""Paper figures, numeric exports and a self-contained evaluation report."""
from __future__ import annotations
import csv
import json
from pathlib import Path


def write_csv(path, rows, fieldnames=None):
    rows=list(rows)
    if not rows and fieldnames is None:
        return
    with Path(path).open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fieldnames or list(rows[0]))
        writer.writeheader();writer.writerows(rows)


def display(value):
    return 'N/A' if value is None else f'{value:.4f}'


def save_report(out, summary, group_metrics, threshold_rows, records, per_image, pr, args):
    import numpy as np
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter
    plt.rcParams.update({'font.family':'DejaVu Serif','font.size':10,'axes.labelsize':10,
                         'legend.fontsize':8,'axes.spines.top':False,'axes.spines.right':False,
                         'pdf.fonttype':42,'ps.fonttype':42,'svg.fonttype':'none','savefig.dpi':args.dpi})
    figures=out/'figures';figures.mkdir()
    tables=out/'tables';tables.mkdir()
    write_csv(out/'per_image.csv',per_image)
    write_csv(out/'false_positive_no_ball.csv',[r for r in per_image if r['gt_boxes']==0 and r['predicted_boxes']>0],list(per_image[0]))
    group_rows=[]
    for name,m in group_metrics.items():
        group_rows.append({'scene':name,**{k:m[k] for k in ('images','gt_boxes','mAP50','mAP50_95','precision','recall','F1','no_ball_images','no_ball_false_positive_images','no_ball_false_positive_rate')}})
    write_csv(tables/'scene_metrics.csv',group_rows)
    curve_keys=('confidence','precision','recall','F1','no_ball_false_positive_rate','fp_boxes_per_image','TP','FP','FN')
    write_csv(tables/'confidence_curves.csv',[{k:r[k] for k in curve_keys} for r in threshold_rows])
    if pr is not None:
        write_csv(tables/'pr_curve.csv',({'recall':r,'precision_envelope':p} for r,p in zip(pr['recall'],pr['precision_envelope'])))
    metrics=summary['metrics']
    write_csv(tables/'ap_by_iou.csv',({'iou':round(.5+i*.05,2),'AP':ap} for i,ap in enumerate(metrics['ap_per_iou'])))
    names=[]
    def save(fig,name):
        for fmt in args.formats.split(','):
            fig.savefig(figures/f'{name}.{fmt}',bbox_inches='tight')
        plt.close(fig);names.append(name)
    def probability_axis(ax):
        ax.set_ylim(0,1.02);ax.grid(alpha=.2,linewidth=.5)
    fig,ax=plt.subplots(figsize=(3.6,3.1))
    if pr is not None:
        ax.plot(pr['recall'],pr['precision_envelope'],color='#0072B2',lw=1.6,label=f"AP50 = {metrics['mAP50']:.3f}");ax.legend(loc='lower left')
    else:ax.text(.5,.5,'Not defined: no ground-truth balls',ha='center',va='center',transform=ax.transAxes,wrap=True)
    ax.set(xlabel='Recall',ylabel='Precision',xlim=(0,1));probability_axis(ax);save(fig,'pr_curve')
    fig,ax=plt.subplots(figsize=(3.6,3.1))
    for key,label,color in [('precision','Precision','#0072B2'),('recall','Recall','#D55E00'),('F1','F1','#009E73')]:
        ax.plot([r['confidence'] for r in threshold_rows],[np.nan if r[key] is None else r[key] for r in threshold_rows],label=label,color=color,lw=1.4)
    ax.axvline(args.conf,color='.5',ls='--',lw=.8,label=f'Operating point {args.conf:g}');ax.legend();ax.set(xlabel='Confidence threshold',ylabel='Score',xlim=(args.min_conf,1));probability_axis(ax);save(fig,'confidence_curves')
    fig,ax=plt.subplots(figsize=(3.6,3.1))
    ax.plot([r['confidence'] for r in threshold_rows],[np.nan if r['no_ball_false_positive_rate'] is None else r['no_ball_false_positive_rate'] for r in threshold_rows],color='#D55E00',lw=1.6)
    ax.axvline(args.conf,color='.5',ls='--',lw=.8);ax.set(xlabel='Confidence threshold',ylabel='No-ball false-positive image rate',xlim=(args.min_conf,1));probability_axis(ax)
    if not metrics['no_ball_images']:ax.text(.5,.5,'Not defined: no negative images',ha='center',transform=ax.transAxes)
    save(fig,'no_ball_fpr_curve')
    fig,ax=plt.subplots(figsize=(3.6,3.1))
    ax.plot(np.linspace(.5,.95,10),[np.nan if x is None else x for x in metrics['ap_per_iou']],marker='o',ms=3,color='#0072B2',lw=1.3)
    ax.set(xlabel='Matching IoU',ylabel='Average precision',xlim=(.49,.96));probability_axis(ax);save(fig,'ap_vs_iou')
    fig,ax=plt.subplots(figsize=(3.6,3.1))
    ax.plot([r['fp_boxes_per_image'] for r in threshold_rows],[np.nan if r['recall'] is None else r['recall'] for r in threshold_rows],color='#009E73',lw=1.5)
    ax.set(xlabel='False-positive boxes per image',ylabel='Object recall');probability_axis(ax);save(fig,'froc_curve')
    # Detection background true-negatives are undefined, not a count of empty pixels.
    for name,matrix,xlabels,ylabels in [
        ('detection_confusion_matrix',[[metrics['TP'],metrics['FN']],[metrics['FP'],np.nan]],['Ball','No detection'],['Ball','Background']),
        ('image_presence_confusion_matrix',[[metrics['presence_confusion']['TP'],metrics['presence_confusion']['FN']],
                                           [metrics['presence_confusion']['FP'],metrics['presence_confusion']['TN']]],['Ball present','No ball'],['Ball present','No ball'])]:
        fig,ax=plt.subplots(figsize=(3.6,3.1));array=np.asarray(matrix,dtype=float)
        ax.imshow(np.ma.masked_invalid(array),cmap='Blues',vmin=0,vmax=max(1,np.nanmax(array)))
        for i in range(2):
            for j in range(2):
                value=array[i,j];ax.text(j,i,'N/A' if np.isnan(value) else str(int(value)),ha='center',va='center',color='white' if np.isfinite(value) and value>.5*np.nanmax(array) else 'black')
        ax.set(xticks=[0,1],yticks=[0,1],xticklabels=xlabels,yticklabels=ylabels,xlabel='Predicted',ylabel='Ground truth');save(fig,name)
    fig,ax=plt.subplots(figsize=(11,3.8));labels=list(group_metrics);x=np.arange(len(labels))
    for offset,key,title,color in [(-.30,'mAP50','AP50','#0072B2'),(0,'recall','Recall','#D55E00'),(.30,'no_ball_false_positive_rate','No-ball FPR','#009E73')]:
        vals=[group_metrics[k][key] for k in labels]
        bars=ax.bar(x+offset,[np.nan if v is None else v for v in vals],width=.26,label=title,color=color)
        ax.bar_label(bars,labels=['' if v is None else f'{v:.2%}' for v in vals],padding=3,fontsize=7)
        for j,v in enumerate(vals):
            if v is None:ax.text(x[j]+offset,.025,'NA',rotation=90,ha='center',fontsize=6)
    ax.set(xticks=x,xticklabels=labels,ylabel='Metric value');ax.legend(ncol=3,loc='upper center',bbox_to_anchor=(.5,1.2));probability_axis(ax)
    ax.set_ylim(0,1.10)  # Keep labels above unit-height bars inside the plot.
    ax.yaxis.set_major_formatter(PercentFormatter(xmax=1,decimals=0))
    save(fig,'scene_comparison')
    # A copy-ready LaTeX row deliberately contains explicit operating conditions.
    def tex_escape(value):
        replacements={'\\':r'\textbackslash{}','&':r'\&','%':r'\%','$':r'\$','#':r'\#','_':r'\_','{':r'\{','}':r'\}','~':r'\textasciitilde{}','^':r'\textasciicircum{}'}
        return ''.join(replacements.get(c,c) for c in value)
    row=' & '.join([tex_escape(summary['model_name']),summary['split'],str(metrics['images'])]+[display(metrics[k]) for k in ('mAP50','mAP50_95','precision','recall','F1','no_ball_false_positive_rate')])
    (tables/'paper_row.tex').write_text('% Model & Split & Images & AP50 & AP50--95 & P & R & F1 & No-ball FPR\n'+row+' \\\\\n')
    text=f'''# 足球检测模型评估

- 模型：`{summary['model']}`；模型类别 `{summary['model_class_id']}` 映射为 `0=football`。
- 集合：**{summary['split']}**，{metrics['images']}张；有球{metrics['positive_images']}张、确认无球{metrics['no_ball_images']}张，GT球框{metrics['gt_boxes']}个。
- 数据选择：只纳入双项已审核、有效label、状态为reviewed_annotation/negative_confirmed的图片；跳过{summary['skipped_images']}张。
- 输入尺寸{args.imgsz}，候选置信度下限{args.min_conf}，固定工作阈值{args.conf}，工作指标匹配IoU={args.match_iou}，NMS IoU={args.nms_iou}，max_det={args.max_det}。
- Ultralytics {summary['versions']['ultralytics']}；预测采用rect=False的正方形letterbox，不启用TTA。

| 指标 | 数值 |
| --- | ---: |
'''
    for key in ('mAP50','mAP75','mAP50_95','precision','recall','F1','no_ball_false_positive_rate','fp_boxes_per_image','positive_image_miss_rate'):
        text+=f'| {key} | {display(metrics[key])} |\n'
    text+=f"\n固定工作阈值：TP={metrics['TP']}，FP={metrics['FP']}，FN={metrics['FN']}。无球误报为{metrics['no_ball_false_positive_images']}/{metrics['no_ball_images']}张，Wilson 95%区间：{metrics['no_ball_fpr_wilson95']}。\n"
    text+='''
## 口径

mAP使用全部保留候选、IoU=0.50:0.05:0.95、Ultralytics默认最高IoU一对一匹配及官方ap_per_class/101点插值。单类时mAP就是football AP；这不是含COCO面积分层/crowd规则的完整COCO评测。置信度候选下限会截断极低分召回，须在模型间保持一致。

Precision、Recall、F1、TP/FP/FN、漏检率与无球FPR均在预先指定的固定工作阈值计算，阈值过滤后重新一对一匹配。置信度曲线也是逐阈值重新匹配。JSON额外保存的ultralytics_max_f1_precision/recall来自AP扫阈值摘要，与固定阈值P/R不是同一口径；不得在Test上用它挑选部署阈值。

无球FPR = 无球图片中至少出现一个超过工作置信度的football框的图片数 / 确认无球图片数。一张图误报多个框，分子只计一次；另输出误报框数和每图误报框数。无负样本时该值为null/N/A，不是0。没有GT球的子集AP与Recall为null/N/A，不把它记成成功或0分。

检测混淆矩阵的背景真负数没有定义，该单元显示N/A；图像存在性混淆矩阵可定义TN，但其中“有球”预测不保证定位正确。四项场景是重叠子集，图中缺指标显示NA，不能相加或取均值代替全量指标。报告里Wilson区间仅为图像独立假设下的描述性区间，相邻帧/左右目相关性可能使区间过窄。

P-R图为AP50精度包络；图表默认仅导出PNG，可用--formats指定SVG、PDF或多个格式。场景柱状图在柱顶标注保留两位小数的百分数，未定义指标保持NA；JSON/CSV指标仍以0–1比例保存。曲线原始数值保存在tables/，方便统一排版。单张图片不计算“mAP”；per_image.csv保存匹配数量与误报/漏检，false_positive_no_ball.csv列出固定工作阈值下的无球误报图片（无误报时只含表头）。

## 图表

'''
    for name in names:text+=f'- `figures/{name}`：{args.formats}。\n'
    text+='\n## 复现与运行范围\n\n'
    text+=f"- 是否全量集合：{not summary['partial_split']}。可用集合原有{summary['available_before_limit']}张，实际评估{metrics['images']}张。\n"
    if summary['partial_split']:text+='- **这是limit调试子集，不是完整集合成绩，不能写成完整Val/Test结果。**\n'
    if summary['split']=='train':text+='- **这是训练集拟合表现，不能作为独立泛化或Test结果。**\n'
    text+='- 不把当前Val结果写作Test；部署阈值应在独立Val确定，再固定到Test。\n- 原图、label、dataset.yaml、metadata及模型SHA256和运行参数见inputs_manifest.json；评估结束已重查输入文件未变。\n- predictions.jsonl保留全部候选和GT，可用于后续离线复核；未修改原数据，未生成原数据目录下的.cache。\n'
    text+=f"- 运行时间与后台报告速度：`{summary['runtime']}`。速度含义见metrics.json，包含首次warmup的端到端速度不应直接当作纯推理硬件benchmark。\n"
    (out/'REPORT.md').write_text(text)
    (out/'metrics.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
