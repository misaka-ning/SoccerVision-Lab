"""VPI 2.4 BGR resize qualification only; importing this module runs nothing.

Called by the coordinator's offline script under its serial GPU lock. No NV12
conversion, camera, Torch interop, Engine or Graph is used. Cold, one-shot wall
times are diagnostic, not warmed production preprocessing measurements.

Primary references:
https://docs.nvidia.com/vpi/2.4/python/build/vpi.Image.rescale.html
https://docs.nvidia.com/vpi/2.4/python/build/vpi.asimage.html
https://docs.nvidia.com/vpi/2.4/python/build/vpi.Stream.html
https://docs.nvidia.com/vpi/2.4/sample_rescale.html
"""

import time


_FAILED_OWNERS = []  # Retain storage after failed sync; coordinator must reject/exit worker.


def probe(image, resized_wh):
    """Return a JSON-serializable CUDA/VIC direct-BGR qualification record.

    Only an explicit call imports VPI or submits device work. A successful
    single-image comparison still requires full Val and detector validation.
    The caller owns process timeout/global GPU exclusion; no background work is
    started. All VPI sources remain alive through synchronization and host read.
    """
    import cv2
    import numpy as np

    report = {
        "scope": "one-shot direct BGR8 resize qualification; no pipeline speed claim",
        "vpi_version": None, "input_format": "BGR8", "backends": {},
        "interpolation": "LINEAR", "border": "CLAMP", "conversion": "none",
        "timing": "cold submit/allocation + stream.sync; host wall also includes owned copies and host access",
        "production_candidate_approved": False,
    }
    if _FAILED_OWNERS:
        report.update(status="prior_synchronization_failed", error="reject worker; prior VPI owners retained")
        return report
    try:
        if not isinstance(image, np.ndarray) or image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
            raise ValueError("image must be uint8 HWC BGR3")
        width, height = resized_wh
        if int(width) != width or int(height) != height or width <= 0 or height <= 0:
            raise ValueError("resized_wh must contain positive integer width,height")
        width, height = int(width), int(height)
        report.update(input_shape=list(image.shape), resized_wh=[width, height])
        reference = cv2.resize(image, (width, height), interpolation=cv2.INTER_LINEAR)
    except Exception as error:
        report.update(status="invalid_input", error="%s: %s" % (type(error).__name__, error))
        return report
    try:
        import vpi
    except Exception as error:
        report.update(status="vpi_import_failed", error="%s: %s" % (type(error).__name__, error))
        return report
    report["vpi_version"] = str(getattr(vpi, "__version__", "unknown"))
    abort_remaining = False
    for name in ("CUDA", "VIC"):
        row = {"supported": False, "exact": None, "strict_race_qualified": False,
               "completed_resize_wall_ms": None, "host_to_host_wall_ms": None,
               "error": None, "cleanup_error": None}
        report["backends"][name] = row
        if abort_remaining:
            row["error"] = "not attempted after previous stream synchronization failure"
            continue
        stream = source = output = host = None
        started = time.perf_counter_ns()
        phase = "setup"
        try:
            # Protect the caller and retain the wrapped storage through host read.
            host = np.array(image, dtype=np.uint8, order="C", copy=True)
            stream = vpi.Stream()
            source = vpi.asimage(host, format=vpi.Format.BGR8)
            phase = "submit"
            submitted = time.perf_counter_ns()
            output = source.rescale(size=(width, height), backend=getattr(vpi.Backend, name),
                                    interp=vpi.Interp.LINEAR, border=vpi.Border.CLAMP, stream=stream)
            phase = "synchronize"
            stream.sync()
            row["completed_resize_wall_ms"] = (time.perf_counter_ns() - submitted) / 1e6
            phase = "host_read"
            actual = np.array(output.cpu(), copy=True)
            row["host_to_host_wall_ms"] = (time.perf_counter_ns() - started) / 1e6
            if actual.shape != reference.shape or actual.dtype != np.uint8:
                raise ValueError("unexpected output shape/dtype: %s %s" % (actual.shape, actual.dtype))
            if not np.array_equal(host, image):
                raise ValueError("VPI modified the wrapped source")
            difference = np.abs(actual.astype(np.int16) - reference.astype(np.int16))
            different = int(np.count_nonzero(difference))
            row.update(supported=True, exact=different == 0, max_abs_uint8=int(difference.max()),
                       different_channel_pixels=different, total_channel_pixels=int(difference.size),
                       nonzero_fraction=float(different / difference.size), mean_abs_uint8=float(difference.mean()),
                       decision="needs_full_Val_and_Graph_gate" if different == 0 else "exclude_numerical_mismatch")
        except Exception as error:
            row.update(failed_phase=phase, error="%s: %s" % (type(error).__name__, error),
                       decision="exclude_direct_BGR_probe_failed")
        finally:
            if stream is not None:
                try:
                    stream.sync()
                except Exception as error:
                    row["cleanup_error"] = "%s: %s" % (type(error).__name__, error)
                    row["decision"] = "exclude_sync_failed"
                    row["supported"] = False
                    row["cleanup_owners_retained"] = True
                    _FAILED_OWNERS.append((stream, source, output, host))
                    abort_remaining = True
            # References are released only after the stream synchronization attempt.
            output = source = host = stream = None
    report["status"] = "complete" if not abort_remaining else "synchronization_failed"
    return report
