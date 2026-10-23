"""CPU-only schedule and strict raw-data statistics for E04 single variants."""
import csv
import math


VARIANTS = {'R0': {}, 'A1': {'postprocess': 'a1'}, 'A2': {'postprocess': 'a2'},
            'A1_A2': {'postprocess': 'a1+a2'}, 'B_Graph': {'engine': 'graph'}, 'C2': {'preprocess': 'c2'}}
ORDERS = [('A1', 'A2', 'A1_A2', 'B_Graph', 'C2'),
          ('C2', 'B_Graph', 'A1_A2', 'A2', 'A1'),
          ('A2', 'B_Graph', 'A1', 'C2', 'A1_A2')]
SCOPES = ('execution', 'detector', 'diagnostic', 'system')

COMBINATION_VARIANTS = {'R0': {}, 'A2': {'postprocess': 'a2'},
                        'R4_AB': {'postprocess': 'a2', 'engine': 'graph'},
                        'R5_ABC': {'postprocess': 'a2', 'engine': 'graph', 'preprocess': 'c2'}}
COMBINATION_ORDERS = [('A2', 'R4_AB', 'R5_ABC'),
                      ('R5_ABC', 'A2', 'R4_AB'),
                      ('R4_AB', 'R5_ABC', 'A2')]


def matrix_scopes(matrix):
    if matrix == 'single_components':
        return SCOPES
    if matrix == 'combined_pipeline':
        return ('detector', 'system')
    raise ValueError('Unknown performance matrix: ' + repr(matrix))


def schedule(scopes, matrix='single_components'):
    unknown = set(scopes) - set(matrix_scopes(matrix))
    if unknown:
        raise ValueError('Unknown scope: ' + repr(unknown))
    if matrix == 'combined_pipeline':
        jobs = []
        for scope in matrix_scopes(matrix):
            if scope not in scopes:
                continue
            for index, order in enumerate(COMBINATION_ORDERS, 1):
                for position, variant in enumerate(('R0',) + order + ('R0',)):
                    jobs.append(dict(name='%s_r%d_%02d_%s' % (scope, index, position, variant),
                        scope=scope, variant=variant, switches=COMBINATION_VARIANTS[variant],
                        warmup=100, seconds=60, round=index, position=position, matrix_id=matrix))
        return jobs
    jobs = []
    for scope in SCOPES:
        if scope not in scopes:
            continue
        if scope == 'diagnostic':
            jobs.append(dict(name='diagnostic_C1', scope=scope, variant='C1_probe', switches={'preprocess': 'c1'}, warmup=100, seconds=60))
        elif scope == 'execution':
            for index in range(1, 4):
                for variant in (('b0', 'graph') if index % 2 else ('graph', 'b0')):
                    jobs.append(dict(name='execution_r%d_%s' % (index, variant), scope=scope, variant=variant,
                                     switches={}, warmup=100, seconds=60, round=index))
        else:
            for index, order in enumerate(ORDERS, 1):
                for position, variant in enumerate(('R0',) + order + ('R0',)):
                    jobs.append(dict(name='%s_r%d_%02d_%s' % (scope, index, position, variant), scope=scope,
                                     variant=variant, switches=VARIANTS[variant], warmup=100, seconds=60, round=index, position=position))
    return jobs


def is_baseline_end(spec, specs):
    if spec['scope'] not in ('detector', 'system') or spec['variant'] != 'R0':
        return False
    positions = [x['position'] for x in specs if x['scope'] == spec['scope'] and x.get('round') == spec.get('round')]
    return spec['position'] == max(positions)


def stats(values):
    values = sorted(values)
    if not values or not all(math.isfinite(v) for v in values):
        raise ValueError('Missing/nonfinite raw measurements')
    def percentile(q):
        position = (len(values) - 1) * q
        lower, upper = int(position), math.ceil(position)
        return values[lower] + (values[upper] - values[lower]) * (position - lower)
    return dict(n=len(values), mean=sum(values) / len(values), p50=percentile(.5), p95=percentile(.95), p99=percentile(.99),
                min=values[0], max=values[-1])


def summarize(path, scope):
    with path.open() as stream:
        rows = [{k: float(v) for k, v in row.items()} for row in csv.DictReader(stream)]
    if not rows:
        raise ValueError('No raw rows: ' + str(path))
    result = {k: stats([r[k] for r in rows]) for k in rows[0] if k.endswith('_ms')}
    if scope == 'system':
        elapsed = rows[-1]['cycle_end'] - rows[0]['cycle_start']
        publish = rows[-1]['publish_end'] - rows[0]['publish_end']
        if elapsed <= 0 or publish <= 0:
            raise ValueError('Invalid system timestamps')
        result.update(processing_hz=len(rows) / elapsed, publish_hz=(len(rows) - 1) / publish,
                      hz_sample_seconds=elapsed, publish_sample_seconds=publish,
                      candidate_counts={eye: stats([r[eye + '_candidates'] for r in rows]) for eye in ['left', 'right']})
        if 'measurement_valid' in rows[0]:
            for key in ['measurement_valid', 'tracking_valid', 'track_initialized', 'coasting']:
                if any(r[key] not in (0, 1) for r in rows):
                    raise ValueError('Invalid encoded packet flag: ' + key)
            result['packet_flags'] = {k: dict(count=sum(r[k] for r in rows), fraction=sum(r[k] for r in rows)/len(rows))
                                      for k in ['measurement_valid', 'tracking_valid', 'track_initialized', 'coasting']}
            result['frame_association'] = dict(frame_idx_first=rows[0]['frame_idx'], frame_idx_last=rows[-1]['frame_idx'],
                frame_idx_nonincreasing=sum(b['frame_idx']<=a['frame_idx'] for a,b in zip(rows,rows[1:])),
                timestamp_nonincreasing=sum(b['frame_timestamp_s']<=a['frame_timestamp_s'] for a,b in zip(rows,rows[1:])),
                timestamp_scope='Source read-time relative clock; not SDK exposure time or image-age measurement')
    return result
