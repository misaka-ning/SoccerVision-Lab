"""Process and resume guards. These functions never stop unrelated tasks."""
import datetime
import os
import signal
import subprocess


def run_child(command, stream, lock_fd, on_started, timeout_seconds=240):
    process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True,
                               pass_fds=(lock_fd,))
    try:
        on_started(process.pid)
        return process.wait(timeout=timeout_seconds)
    except BaseException:
        # Only the session/process group created immediately above belongs to us.
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=10)
        raise


def supersede_partial_blocks(jobs, specs, scopes):
    """Keep complete blocks; restart an interrupted paired/bracketed block."""
    groups = {}
    for spec in specs:
        if spec['scope'] not in scopes or 'round' not in spec:
            continue
        groups.setdefault((spec['scope'], spec['round'], spec.get('matrix_id', 'single_components')), set()).add(spec['name'])
    changed = False
    for (scope, round_index, matrix_id), names in groups.items():
        complete = {j['name'] for j in jobs if j['status'] == 'complete' and j.get('matrix_id', 'single_components') == matrix_id}
        if not complete.intersection(names) or names.issubset(complete):
            continue
        for job in jobs:
            if job['name'] in names and job.get('matrix_id', 'single_components') == matrix_id and job['status'] == 'complete':
                job.update(status='superseded_incomplete_block', prior_status='complete',
                           superseded_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                           reason='Resume restarts whole paired/bracketed block; raw data retained')
                changed = True
    return changed
