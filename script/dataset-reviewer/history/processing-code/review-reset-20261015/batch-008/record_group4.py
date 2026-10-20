"""Persist root's actual native visual observations; never edit the dataset."""
import json
from pathlib import Path
W = Path(__file__).resolve().parent / 'group-4'
def record(decisions, pages=(), roi=()):
    p = W / 'head-notes.json'
    obj = json.loads(p.read_text()) if p.exists() else {'decisions': {}, 'actual_opened_full_pages': [], 'actual_opened_roi_pages': []}
    for n, value in decisions.items():
        assert 0 <= int(n) <= 75
        flags, reason, *extra = value
        assert len(flags)==4 and set(flags)<=set('01')
        row = dict(flags=dict(zip(('Small','Occluded','Blurred','No Ball'), flags)), reason=reason, action='keep', scene_certain=True, confidence='high')
        if extra: row.update(extra[0])
        obj['decisions'][str(n)] = row
    for key, subdir, ids in [('actual_opened_full_pages','full',pages), ('actual_opened_roi_pages','roi',roi)]:
        for n in ids:
            v = str(W / subdir / f'page-{n:03d}.png')
            assert Path(v).is_file()
            if v not in obj[key]: obj[key].append(v)
    p.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
