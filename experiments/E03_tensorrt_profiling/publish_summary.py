#!/usr/bin/env python3
"""Render small review artifacts from the provenance-labelled robot summary."""
import csv
import json
import os
from pathlib import Path


def write_csv(path, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    root = Path(__file__).resolve().parent
    data = json.loads((root / 'MEASUREMENT_SUMMARY.json').read_text())
    verified = data['delivery_status'] in ('raw_verified_analysis_complete', 'complete')
    provenance = 'robot_raw_sha256_verified_cpu_reanalysis' if verified else 'robot_analysis_readback_raw_recovery_pending'
    out = root / 'results'
    out.mkdir(exist_ok=True)
    rows = []
    profile = data['module_profiles']
    for artifact in ('legacy', 'new_detailed'):
        for model, result in profile[artifact].items():
            assert abs(sum(result['group_ms']) - result['total_ms']) < 1e-8
            for group, value in zip(profile['groups'], result['group_ms']):
                rows.append(dict(artifact=artifact, model=model, module=group,
                                 mean_profile_ms=value, percent_of_profile=value / result['total_ms'] * 100,
                                 repeats=3, provenance=provenance))
    write_csv(out / 'module_costs.csv', rows)
    rows = []
    for model, result in profile['legacy'].items():
        assert abs(result['l19_core_ms'] + result['l19_auxiliary_ms'] - result['l19_total_ms']) < 1e-8
        rows.append(dict(model=model, core_ms=result['l19_core_ms'], auxiliary_ms=result['l19_auxiliary_ms'],
                         total_ms=result['l19_total_ms'], percent_of_profile=result['l19_total_ms'] / result['total_ms'] * 100,
                         provenance=provenance))
    write_csv(out / 'l19_comparison.csv', rows)
    rows = []
    for artifact in ('legacy', 'new_performance'):
        for model, result in data['normal_cuda_event_ms_per_batch'][artifact].items():
            rows.append(dict(artifact=artifact, model=model, rounds=3, n=result.get('n'),
                             mean_ms=result['mean'], p50_ms=result['p50'], p95_ms=result['p95'], p99_ms=result['p99'],
                             raw_recovered_locally=verified or artifact == 'legacy'))
    write_csv(out / 'normal_timings_summary.csv', rows)

    os.environ.setdefault('MPLCONFIGDIR', '/tmp/e03-matplotlib')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np

    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10,
                         'axes.spines.top': False, 'axes.spines.right': False})
    fig, (ax, detail) = plt.subplots(1, 2, figsize=(11, 4.9), gridspec_kw={'width_ratios': [1.5, 1]})
    colors = ['#326B9B', '#4C9F91', '#9766AC', '#DBA546', '#89949E']
    groups = ['Backbone excl. Attention', 'Neck excl. embedded PSA', 'Attention blocks', 'Detect head', 'Reformat / Copy']
    left = np.zeros(2)
    for index, (group, color) in enumerate(zip(groups, colors)):
        values = [profile['legacy'][m]['group_ms'][index] for m in ('E01', 'E02')]
        ax.barh(['E01', 'E02'], values, left=left, label=group, color=color, height=.5)
        for i, value in enumerate(values):
            ax.text(left[i] + value / 2, i, f'{value:.2f}', ha='center', va='center', color='white', fontsize=9)
        left += values
    ax.invert_yaxis()
    ax.set_xlim(0, 30)
    ax.set_xlabel('Sum of mean layer times (ms / batch=2)')
    ax.set_title('Legacy engines: where the GPU layer time goes', loc='left', fontsize=11)
    ax.legend(loc='upper left', bbox_to_anchor=(0, -.24), frameon=False, fontsize=9, ncol=2)

    core = [profile['legacy'][m]['l19_core_ms'] for m in ('E01', 'E02')]
    aux = [profile['legacy'][m]['l19_auxiliary_ms'] for m in ('E01', 'E02')]
    detail.bar(['E01', 'E02'], core, color='#326B9B', label='L19 core', width=.55)
    detail.bar(['E01', 'E02'], aux, bottom=core, color='#89949E', label='L19 auxiliary', width=.55)
    for i, (c, a) in enumerate(zip(core, aux)):
        detail.text(i, c / 2, f'{c:.3f}', ha='center', va='center', color='white')
        detail.text(i, c + a / 2, f'{a:.3f}', ha='center', va='center', color='white', fontsize=9)
        detail.text(i, c + a + .025, f'{c + a:.3f} ms', ha='center', fontsize=10)
    detail.set_ylim(0, 1.7)
    detail.set_ylabel('Mean layer time (ms / batch=2)')
    detail.set_title('L19: +8.1% after narrowing', loc='left', fontsize=11)
    detail.legend(frameon=False, loc='upper left', bbox_to_anchor=(0, -.24), fontsize=9)
    fig.suptitle('E03 | Orin NX, 25W, dynamic clocks, GPU cap 408 MHz', x=.06, ha='left', fontsize=13)
    fig.subplots_adjust(left=.06, right=.98, top=.83, bottom=.3, wspace=.28)
    recovery_note = 'Complete robot archive verified (625 file hashes).' if verified else 'Robot readback; full raw recovery pending.'
    fig.text(.06, .025, 'Three profiles per engine. Profile sums differ from normal latency. ' + recovery_note, fontsize=8, color='#555555')
    fig.savefig(out / 'module_costs.png', dpi=180)
    fig.savefig(out / 'module_costs.pdf')
    plt.close(fig)
    print(out)


if __name__ == '__main__':
    main()
