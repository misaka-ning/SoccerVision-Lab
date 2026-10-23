# Ultralytics AGPL-3.0 License - https://ultralytics.com/license
# Frozen function bodies extracted verbatim from robot Ultralytics 8.3.159 ops.py.
# Source ops.py SHA256: 26487cd2e8f28b45c343036a094632a261fc350d78e401fd7683144bc56df061
# Original project fallback extracted verbatim from the frozen yolo.py.
# Test-only Golden Reference; do not modify to make a candidate pass.
import logging
import time
import numpy as np
import torch
LOGGER = logging.getLogger(__name__)

def scale_boxes(img1_shape, boxes, img0_shape, ratio_pad=None, padding: bool = True, xywh: bool = False):
    """
    Rescale bounding boxes from one image shape to another.

    Rescales bounding boxes from img1_shape to img0_shape, accounting for padding and aspect ratio changes.
    Supports both xyxy and xywh box formats.

    Args:
        img1_shape (tuple): Shape of the source image (height, width).
        boxes (torch.Tensor): Bounding boxes to rescale in format (N, 4).
        img0_shape (tuple): Shape of the target image (height, width).
        ratio_pad (tuple, optional): Tuple of (ratio, pad) for scaling. If None, calculated from image shapes.
        padding (bool): Whether boxes are based on YOLO-style augmented images with padding.
        xywh (bool): Whether box format is xywh (True) or xyxy (False).

    Returns:
        (torch.Tensor): Rescaled bounding boxes in the same format as input.
    """
    if ratio_pad is None:  # calculate from img0_shape
        gain = min(img1_shape[0] / img0_shape[0], img1_shape[1] / img0_shape[1])  # gain  = old / new
        pad = (
            round((img1_shape[1] - img0_shape[1] * gain) / 2 - 0.1),
            round((img1_shape[0] - img0_shape[0] * gain) / 2 - 0.1),
        )  # wh padding
    else:
        gain = ratio_pad[0][0]
        pad = ratio_pad[1]

    if padding:
        boxes[..., 0] -= pad[0]  # x padding
        boxes[..., 1] -= pad[1]  # y padding
        if not xywh:
            boxes[..., 2] -= pad[0]  # x padding
            boxes[..., 3] -= pad[1]  # y padding
    boxes[..., :4] /= gain
    return clip_boxes(boxes, img0_shape)


def non_max_suppression(
    prediction,
    conf_thres: float = 0.25,
    iou_thres: float = 0.45,
    classes=None,
    agnostic: bool = False,
    multi_label: bool = False,
    labels=(),
    max_det: int = 300,
    nc: int = 0,  # number of classes (optional)
    max_time_img: float = 0.05,
    max_nms: int = 30000,
    max_wh: int = 7680,
    in_place: bool = True,
    rotated: bool = False,
    end2end: bool = False,
    return_idxs: bool = False,
):
    """
    Perform non-maximum suppression (NMS) on prediction results.

    Applies NMS to filter overlapping bounding boxes based on confidence and IoU thresholds. Supports multiple
    detection formats including standard boxes, rotated boxes, and masks.

    Args:
        prediction (torch.Tensor): Predictions with shape (batch_size, num_classes + 4 + num_masks, num_boxes)
            containing boxes, classes, and optional masks.
        conf_thres (float): Confidence threshold for filtering detections. Valid values are between 0.0 and 1.0.
        iou_thres (float): IoU threshold for NMS filtering. Valid values are between 0.0 and 1.0.
        classes (List[int], optional): List of class indices to consider. If None, all classes are considered.
        agnostic (bool): Whether to perform class-agnostic NMS.
        multi_label (bool): Whether each box can have multiple labels.
        labels (List[List[Union[int, float, torch.Tensor]]]): A priori labels for each image.
        max_det (int): Maximum number of detections to keep per image.
        nc (int): Number of classes. Indices after this are considered masks.
        max_time_img (float): Maximum time in seconds for processing one image.
        max_nms (int): Maximum number of boxes for torchvision.ops.nms().
        max_wh (int): Maximum box width and height in pixels.
        in_place (bool): Whether to modify the input prediction tensor in place.
        rotated (bool): Whether to handle Oriented Bounding Boxes (OBB).
        end2end (bool): Whether the model is end-to-end and doesn't require NMS.
        return_idxs (bool): Whether to return the indices of kept detections.

    Returns:
        output (List[torch.Tensor]): List of detections per image with shape (num_boxes, 6 + num_masks)
            containing (x1, y1, x2, y2, confidence, class, mask1, mask2, ...).
        keepi (List[torch.Tensor]): Indices of kept detections if return_idxs=True.
    """
    import torchvision  # scope for faster 'import ultralytics'

    # Checks
    assert 0 <= conf_thres <= 1, f"Invalid Confidence threshold {conf_thres}, valid values are between 0.0 and 1.0"
    assert 0 <= iou_thres <= 1, f"Invalid IoU {iou_thres}, valid values are between 0.0 and 1.0"
    if isinstance(prediction, (list, tuple)):  # YOLOv8 model in validation model, output = (inference_out, loss_out)
        prediction = prediction[0]  # select only inference output
    if classes is not None:
        classes = torch.tensor(classes, device=prediction.device)

    if prediction.shape[-1] == 6 or end2end:  # end-to-end model (BNC, i.e. 1,300,6)
        output = [pred[pred[:, 4] > conf_thres][:max_det] for pred in prediction]
        if classes is not None:
            output = [pred[(pred[:, 5:6] == classes).any(1)] for pred in output]
        return output

    bs = prediction.shape[0]  # batch size (BCN, i.e. 1,84,6300)
    nc = nc or (prediction.shape[1] - 4)  # number of classes
    extra = prediction.shape[1] - nc - 4  # number of extra info
    mi = 4 + nc  # mask start index
    xc = prediction[:, 4:mi].amax(1) > conf_thres  # candidates
    xinds = torch.stack([torch.arange(len(i), device=prediction.device) for i in xc])[..., None]  # to track idxs

    # Settings
    # min_wh = 2  # (pixels) minimum box width and height
    time_limit = 2.0 + max_time_img * bs  # seconds to quit after
    multi_label &= nc > 1  # multiple labels per box (adds 0.5ms/img)

    prediction = prediction.transpose(-1, -2)  # shape(1,84,6300) to shape(1,6300,84)
    if not rotated:
        if in_place:
            prediction[..., :4] = xywh2xyxy(prediction[..., :4])  # xywh to xyxy
        else:
            prediction = torch.cat((xywh2xyxy(prediction[..., :4]), prediction[..., 4:]), dim=-1)  # xywh to xyxy

    t = time.time()
    output = [torch.zeros((0, 6 + extra), device=prediction.device)] * bs
    keepi = [torch.zeros((0, 1), device=prediction.device)] * bs  # to store the kept idxs
    for xi, (x, xk) in enumerate(zip(prediction, xinds)):  # image index, (preds, preds indices)
        # Apply constraints
        # x[((x[:, 2:4] < min_wh) | (x[:, 2:4] > max_wh)).any(1), 4] = 0  # width-height
        filt = xc[xi]  # confidence
        x, xk = x[filt], xk[filt]

        # Cat apriori labels if autolabelling
        if labels and len(labels[xi]) and not rotated:
            lb = labels[xi]
            v = torch.zeros((len(lb), nc + extra + 4), device=x.device)
            v[:, :4] = xywh2xyxy(lb[:, 1:5])  # box
            v[range(len(lb)), lb[:, 0].long() + 4] = 1.0  # cls
            x = torch.cat((x, v), 0)

        # If none remain process next image
        if not x.shape[0]:
            continue

        # Detections matrix nx6 (xyxy, conf, cls)
        box, cls, mask = x.split((4, nc, extra), 1)

        if multi_label:
            i, j = torch.where(cls > conf_thres)
            x = torch.cat((box[i], x[i, 4 + j, None], j[:, None].float(), mask[i]), 1)
            xk = xk[i]
        else:  # best class only
            conf, j = cls.max(1, keepdim=True)
            filt = conf.view(-1) > conf_thres
            x = torch.cat((box, conf, j.float(), mask), 1)[filt]
            xk = xk[filt]

        # Filter by class
        if classes is not None:
            filt = (x[:, 5:6] == classes).any(1)
            x, xk = x[filt], xk[filt]

        # Check shape
        n = x.shape[0]  # number of boxes
        if not n:  # no boxes
            continue
        if n > max_nms:  # excess boxes
            filt = x[:, 4].argsort(descending=True)[:max_nms]  # sort by confidence and remove excess boxes
            x, xk = x[filt], xk[filt]

        # Batched NMS
        c = x[:, 5:6] * (0 if agnostic else max_wh)  # classes
        scores = x[:, 4]  # scores
        if rotated:
            boxes = torch.cat((x[:, :2] + c, x[:, 2:4], x[:, -1:]), dim=-1)  # xywhr
            i = nms_rotated(boxes, scores, iou_thres)
        else:
            boxes = x[:, :4] + c  # boxes (offset by class)
            i = torchvision.ops.nms(boxes, scores, iou_thres)  # NMS
        i = i[:max_det]  # limit detections

        output[xi], keepi[xi] = x[i], xk[i].reshape(-1)
        if (time.time() - t) > time_limit:
            LOGGER.warning(f"NMS time limit {time_limit:.3f}s exceeded")
            break  # time limit exceeded

    return (output, keepi) if return_idxs else output


def clip_boxes(boxes, shape):
    """
    Clip bounding boxes to image boundaries.

    Args:
        boxes (torch.Tensor | numpy.ndarray): Bounding boxes to clip.
        shape (tuple): Image shape as (height, width).

    Returns:
        (torch.Tensor | numpy.ndarray): Clipped bounding boxes.
    """
    if isinstance(boxes, torch.Tensor):  # faster individually (WARNING: inplace .clamp_() Apple MPS bug)
        boxes[..., 0] = boxes[..., 0].clamp(0, shape[1])  # x1
        boxes[..., 1] = boxes[..., 1].clamp(0, shape[0])  # y1
        boxes[..., 2] = boxes[..., 2].clamp(0, shape[1])  # x2
        boxes[..., 3] = boxes[..., 3].clamp(0, shape[0])  # y2
    else:  # np.array (faster grouped)
        boxes[..., [0, 2]] = boxes[..., [0, 2]].clip(0, shape[1])  # x1, x2
        boxes[..., [1, 3]] = boxes[..., [1, 3]].clip(0, shape[0])  # y1, y2
    return boxes


def xywh2xyxy(x):
    """
    Convert bounding box coordinates from (x, y, width, height) format to (x1, y1, x2, y2) format where (x1, y1) is the
    top-left corner and (x2, y2) is the bottom-right corner. Note: ops per 2 channels faster than per channel.

    Args:
        x (np.ndarray | torch.Tensor): Input bounding box coordinates in (x, y, width, height) format.

    Returns:
        (np.ndarray | torch.Tensor): Bounding box coordinates in (x1, y1, x2, y2) format.
    """
    assert x.shape[-1] == 4, f"input shape last dimension expected 4 but input shape is {x.shape}"
    y = empty_like(x)  # faster than clone/copy
    xy = x[..., :2]  # centers
    wh = x[..., 2:] / 2  # half width-height
    y[..., :2] = xy - wh  # top left xy
    y[..., 2:] = xy + wh  # bottom right xy
    return y


def empty_like(x):
    """Create empty torch.Tensor or np.ndarray with same shape as input and float32 dtype."""
    return (
        torch.empty_like(x, dtype=torch.float32) if isinstance(x, torch.Tensor) else np.empty_like(x, dtype=np.float32)
    )


def nms_fallback(boxes, scores, iou_threshold):
        if boxes.numel() == 0:
            return torch.empty((0,), dtype=torch.long, device=boxes.device)

        x1, y1, x2, y2 = boxes.unbind(dim=1)
        areas = (x2 - x1).clamp(min=0) * (y2 - y1).clamp(min=0)
        order = scores.argsort(descending=True)
        keep = []

        while order.numel() > 0:
            current = order[0]
            keep.append(current)
            if order.numel() == 1:
                break

            rest = order[1:]
            xx1 = torch.maximum(x1[current], x1[rest])
            yy1 = torch.maximum(y1[current], y1[rest])
            xx2 = torch.minimum(x2[current], x2[rest])
            yy2 = torch.minimum(y2[current], y2[rest])
            inter = (xx2 - xx1).clamp(min=0) * (yy2 - yy1).clamp(min=0)
            union = areas[current] + areas[rest] - inter
            iou = torch.where(union > 0, inter / union, torch.zeros_like(inter))
            order = rest[iou <= iou_threshold]

        return torch.stack(keep) if keep else torch.empty((0,), dtype=torch.long, device=boxes.device)
