"""Single-class detection metrics; Ultralytics AP and explicit operating points."""
from __future__ import annotations
import math
import numpy as np

IOUS = np.linspace(.5, .95, 10)


def box_iou(gt, pred):
    gt, pred = np.asarray(gt, dtype=float).reshape(-1,4), np.asarray(pred, dtype=float).reshape(-1,4)
    intersection = np.maximum(0, np.minimum(gt[:,None,2:],pred[None,:,2:])-np.maximum(gt[:,None,:2],pred[None,:,:2])).prod(2)
    return intersection / (np.maximum(0,gt[:,2:]-gt[:,:2]).prod(1)[:,None] + np.maximum(0,pred[:,2:]-pred[:,:2]).prod(1)[None,:] - intersection + 1e-7)


def match(iou, thresholds=IOUS):
    """Ultralytics default highest-IoU, one-to-one matching; no Hungarian matching."""
    correct = np.zeros((iou.shape[1], len(thresholds)), dtype=bool)
    for i, threshold in enumerate(thresholds):
        pairs = np.array(np.nonzero(iou >= threshold)).T
        if len(pairs):
            if len(pairs) > 1:
                pairs = pairs[iou[pairs[:,0],pairs[:,1]].argsort()[::-1]]
                pairs = pairs[np.unique(pairs[:,1], return_index=True)[1]]
                pairs = pairs[np.unique(pairs[:,0], return_index=True)[1]]
            correct[pairs[:,1],i] = True
    return correct


def ratio(a, b):
    return float(a/b) if b else None


def wilson(success, total):
    if not total:
        return None
    z = 1.959963984540054
    p = success/total
    center = (p+z*z/(2*total))/(1+z*z/total)
    half = z*math.sqrt(p*(1-p)/total+z*z/(4*total*total))/(1+z*z/total)
    return [max(0.,center-half), min(1.,center+half)]


def prepare(records):
    result = []
    for row in records:
        item = dict(row)
        item['scores'] = np.asarray(row['scores'],dtype=float)
        item['iou'] = box_iou(row['gt'],row['boxes'])
        item['correct'] = match(item['iou'])
        result.append(item)
    return result


def operating(records, confidence, iou_threshold):
    tp=fp=fn=negative_images=negative_fp_images=negative_fp_boxes=positive_images=positive_missed_images=0
    presence_tp=presence_fp=presence_fn=presence_tn=0
    for row in records:
        keep = row['scores'] >= confidence
        count = int(keep.sum())
        targets = len(row['gt'])
        hits = int(match(row['iou'][:,keep], [iou_threshold]).sum())
        tp += hits; fp += count-hits; fn += targets-hits
        if targets:
            positive_images += 1
            positive_missed_images += hits == 0
            presence_tp += count > 0
            presence_fn += count == 0
        else:
            negative_images += 1
            negative_fp_images += count > 0
            negative_fp_boxes += count
            presence_fp += count > 0
            presence_tn += count == 0
    precision = ratio(tp,tp+fp) if tp+fp else (0. if tp+fn else None)
    recall = ratio(tp,tp+fn)
    return dict(confidence=float(confidence), match_iou=float(iou_threshold), TP=tp,FP=fp,FN=fn,
                precision=precision,recall=recall,F1=ratio(2*tp,2*tp+fp+fn),
                images=len(records),gt_boxes=tp+fn,predicted_boxes=tp+fp,
                no_ball_images=negative_images,no_ball_false_positive_images=negative_fp_images,
                no_ball_false_positive_rate=ratio(negative_fp_images,negative_images),
                no_ball_fpr_wilson95=wilson(negative_fp_images,negative_images),
                no_ball_false_positive_boxes=negative_fp_boxes,
                no_ball_fp_boxes_per_image=ratio(negative_fp_boxes,negative_images),
                fp_boxes_per_image=ratio(fp,len(records)),
                positive_images=positive_images,positive_images_with_no_matched_ball=positive_missed_images,
                positive_image_miss_rate=ratio(positive_missed_images,positive_images),
                presence_confusion=dict(TP=presence_tp,FP=presence_fp,FN=presence_fn,TN=presence_tn))


def average_precision(records):
    targets = sum(len(r['gt']) for r in records)
    if not targets:
        return dict(mAP50=None,mAP75=None,mAP50_95=None,ap_per_iou=[None]*10), None
    from ultralytics.utils.metrics import ap_per_class
    correct = np.concatenate([r['correct'] for r in records],axis=0)
    scores = np.concatenate([r['scores'] for r in records])
    values = ap_per_class(correct,scores,np.zeros(len(scores)),np.zeros(targets),plot=False,names={0:'football'})
    ap = values[5][0]
    summary = dict(mAP50=float(ap[0]),mAP75=float(ap[5]),mAP50_95=float(ap.mean()),ap_per_iou=ap.tolist(),
                   ultralytics_max_f1_precision=float(values[2][0]),ultralytics_max_f1_recall=float(values[3][0]))
    # Raw confidence curves are recomputed separately at the requested matching IoU.
    return summary, dict(recall=values[10].tolist(),precision_envelope=values[11][0].tolist())


def summarize(records, confidence, iou_threshold):
    ap, pr = average_precision(records)
    return {**ap,**operating(records,confidence,iou_threshold)}, pr


def groups(records):
    return {'All':records, **{key:[r for r in records if r['flags'][key]] for key in ('Small','Occluded','Blurred','No Ball')},
            'No difficulty':[r for r in records if not any(r['flags'].values())]}
