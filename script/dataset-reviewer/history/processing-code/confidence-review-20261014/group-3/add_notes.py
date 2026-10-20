import json,sys
p='/home/misaka/workspace/dataset_processing/confidence-review-20261014/group-3/visual-notes.json'
d=json.load(open(p));u=json.loads(sys.argv[1])
for k,v in u.items():
 if isinstance(v,list):d.setdefault(k,[]).extend(v)
 elif isinstance(v,dict):d.setdefault(k,{}).update(v)
 else:d[k]=v
json.dump(d,open(p,'w'),ensure_ascii=False,indent=2)
