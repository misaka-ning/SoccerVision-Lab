225: def get_hash(paths: list[str]) -> str:
226:     """Return a hash of paths and their file sizes and modification times."""
227:     h = __import__("hashlib").sha256()
228:     for p in paths:
229:         h.update(p.encode())
230:         h.update(b"\0")
231:         try:
232:             stat = os.stat(p)
233:         except OSError:
234:             h.update(b"\0")
235:             continue
236:         h.update(f"{stat.st_size}:{stat.st_mtime_ns}".encode())
237:         h.update(b"\0")
238:     return h.hexdigest()
239: 
240: 

432:     im_file, lb_file, prefix, keypoint, num_cls, nkpt, ndim, single_cls = args
433:     # Number (missing, found, empty, corrupt), message, segments, keypoints
434:     nm, nf, ne, nc, msg, segments, keypoints = 0, 0, 0, 0, "", [], None
435:     try:
436:         # Verify images
437:         msg, shape = check_image(im_file)
438:         msg = f"{prefix}{msg}" if msg else ""
439: 
440:         # Verify labels
441:         if os.path.isfile(lb_file):
442:             nf = 1  # label found
443:             with open(lb_file, encoding="utf-8") as f:
444:                 lb = [x.split() for x in f.read().strip().splitlines() if x.strip()]
445:                 if nkpt and not keypoint:  # pose labels for a box task: keep the box, drop the keypoints
446:                     lb = [x[:5] if len(x) == 5 + nkpt * ndim else x for x in lb]
447:                 if any(len(x) > 6 for x in lb) and (not keypoint):  # is segment
448:                     assert not any(len(x) == 5 for x in lb), "labels mix segment and detection rows"
449:                     classes = np.array([x[0] for x in lb], dtype=np.float32)
450:                     segments = [np.array(x[1:], dtype=np.float32).reshape(-1, 2) for x in lb]  # (cls, xy1...)
451:                     lb = np.concatenate((classes.reshape(-1, 1), segments2boxes(segments)), 1)  # (cls, xywh)
452:                 lb = np.array(lb, dtype=np.float32)
453:             if nl := len(lb):
454:                 if keypoint:
455:                     assert lb.shape[1] == (5 + nkpt * ndim), f"labels require {(5 + nkpt * ndim)} columns each"
456:                     points = lb[:, 5:].reshape(-1, ndim)[:, :2]
457:                 else:
458:                     assert lb.shape[1] == 5, f"labels require 5 columns, {lb.shape[1]} columns detected"
459:                     points = lb[:, 1:]
460:                 # Coordinate points check with 1% tolerance
461:                 assert points.max() <= 1.01, f"non-normalized or out of bounds coordinates {points[points > 1.01]}"
462:                 assert lb.min() >= -0.01, f"negative class labels or coordinate {lb[lb < -0.01]}"
463:                 assert (lb[:, 0] % 1 == 0).all(), f"non-integer class labels {lb[:, 0][lb[:, 0] % 1 != 0]}"
464: 
465:                 # All labels
466:                 max_cls = 0 if single_cls else lb[:, 0].max()  # max class index
467:                 assert max_cls < num_cls, (
468:                     f"Label class {int(max_cls)} exceeds dataset class count {num_cls}. "
469:                     f"Possible class labels are 0-{num_cls - 1}"
470:                 )
471:                 _, i = np.unique(lb, axis=0, return_index=True)
472:                 if len(i) < nl and segments:  # distinct polygons can share a class and box
473:                     rows = np.array([c.tobytes() + s.tobytes() for c, s in zip(lb[:, 0], segments)], dtype=object)
474:                     _, i = np.unique(rows, return_index=True)
475:                 if len(i) < nl:  # duplicate row check
476:                     lb = lb[i]  # remove duplicates
477:                     if segments:
478:                         segments = [segments[x] for x in i]
479:                     msg = f"{prefix}{im_file}: {nl - len(i)} duplicate labels removed"
480:             else:
481:                 ne = 1  # label empty
482:                 lb = np.zeros((0, (5 + nkpt * ndim) if keypoint else 5), dtype=np.float32)
483:         else:
484:             nm = 1  # label missing
485:             lb = np.zeros((0, (5 + nkpt * ndim) if keypoint else 5), dtype=np.float32)
486:         if keypoint:
487:             keypoints = lb[:, 5:].reshape(-1, nkpt, ndim)
488:             if ndim == 2:
489:                 kpt_mask = np.where((keypoints[..., 0] < 0) | (keypoints[..., 1] < 0), 0.0, 1.0).astype(np.float32)
490:                 keypoints = np.concatenate([keypoints, kpt_mask[..., None]], axis=-1)  # (nl, nkpt, 3)
491:         lb = lb[:, :5]
492:         return im_file, lb, shape, segments, keypoints, nm, nf, ne, nc, msg
493:     except Exception as e:
494:         nc = 1
495:         msg = f"{prefix}{im_file}: ignoring corrupt image/label: {e}"
496:         return [None, None, None, None, None, nm, nf, ne, nc, msg]
497: 
498: 
499: def visualize_image_annotations(image_path: str, txt_path: str, label_map: dict[int, str]):
500:     """Visualize YOLO detection annotations (bounding boxes and class labels) on an image.

959: def load_dataset_cache_file(path: Path) -> dict:
960:     """Load an Ultralytics *.cache dictionary from path.
961: 
962:     Args:
963:         path (Path): Path to the *.cache file.
964: 
965:     Returns:
966:         (dict): The loaded cache dictionary.
967:     """
968:     import gc
969: 
970:     gc.disable()  # reduce pickle load time https://github.com/ultralytics/ultralytics/pull/1585
971:     try:
972:         return np.load(str(path), allow_pickle=True).item()  # load dict
973:     finally:
974:         gc.enable()  # also when loading raises, e.g. no cache file yet
975: 
976: 
977: def save_dataset_cache_file(prefix: str, path: Path, x: dict, version: str):
978:     """Save an Ultralytics dataset *.cache dictionary x to path.
979: 
980:     Args:
981:         prefix (str): Prefix for log messages.
982:         path (Path): Path to save the *.cache file.
983:         x (dict): Cache dictionary to save. A 'version' key is added in place.
984:         version (str): Cache version string.
985:     """
986:     x["version"] = version  # add cache version
987:     if is_dir_writeable(path.parent):
988:         if path.exists():
989:             path.unlink()  # remove *.cache file if exists
990:         try:
991:             with open(str(path), "wb") as file:  # context manager here fixes windows async np.save bug
992:                 np.save(file, x)
993:             LOGGER.info(f"{prefix}New cache created: {path}")
994:         except Exception as e:
995:             Path(path).unlink(missing_ok=True)  # remove partially written file
996:             LOGGER.warning(f"{prefix}Failed to save cache to {path}: {e}")
997:     else:
998:         LOGGER.warning(f"{prefix}Cache directory {path.parent} is not writable, cache not saved.")
