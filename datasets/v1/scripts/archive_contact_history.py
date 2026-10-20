from common import *

def main():
 rows={r['filename']:r for r in load(ROOT/'analysis/source_inventory.json')}
 recovered=[]
 for name in ['round1','round2']:
  directory=ROOT/'analysis'/name
  segments={s['segment_id']:s for s in load(directory/'segments.json')}
  pages=load(directory/'segment_contact_pages.json');(directory/'evidence').mkdir(exist_ok=True)
  for p in pages:
   sid=Path(p['path']).stem.split('-')[-1];s=segments[sid];display=[]
   for filename in p['images']:
    r=dict(rows[filename]);r['display_role']='CORE' if s['start_seconds']<=r['seconds']<=s['end_seconds'] else 'BUFF';display.append(r)
   dest=directory/'evidence'/Path(p['path']).name
   if not dest.exists():
    contact(display,dest,f'{sid} final holdout core and adaptive buffers / one physical session',cols=6,tile_w=224,tile_h=126)
   assert sha(dest)==p['sha256'],f'Historical contact identity differs: {dest}'
   p['archived_copy']=str(dest.relative_to(ROOT));recovered.append(p['archived_copy'])
  save(directory/'segment_contact_pages.json',pages)
 save(ROOT/'analysis/archived_contact_history.json',dict(historical_contact_sheets=recovered,all_match_original_sha256=True))
 print(json.dumps(dict(pages=len(recovered),historical_sha256_match=True)))

if __name__=='__main__':main()
