"""Independent check of column reading: same company, row and period read from different releases should agree.

Run from the repo root: PYTHONPATH=. python scripts/audits/cross_release_columns.py
"""
import json,re
from collections import Counter,defaultdict
from app.config import get_settings
from app.generation.columns import known_periods,split_row,_chunk_headers,_FLAT_VALUE
from app.ingestion.models import Chunk
s=get_settings(); rel=[Chunk(**json.loads(l)) for l in open(s.processed_dir/'chunks_earnings.jsonl',encoding='utf-8')]
seen=defaultdict(lambda:defaultdict(set)); V=re.compile(r'\(?\$?\d[\d,]{3,}\)?')
for c in rel:
    if c.chunk_type!='table' or not known_periods(c): continue
    md,flat=_chunk_headers(c)
    for row in c.text.split('\n'):
        items=[]
        if md and row.startswith('|') and not row.startswith('|---'):
            cs=split_row(row)
            if len(cs)==len(md) and cs[0]: items=[(cs[0],md[j],cs[j]) for j in range(len(md)) if md[j] and V.fullmatch(cs[j])]
        elif flat:
            labels,yoy=flat; toks=row.split(); w=len(labels)+yoy
            for i in range(1,len(toks)-w+1):
                if all(_FLAT_VALUE.fullmatch(t) for t in toks[i:i+w]) and not _FLAT_VALUE.fullmatch(toks[i-1]) and (i+w==len(toks) or not _FLAT_VALUE.fullmatch(toks[i+w])):
                    name=' '.join(t for t in toks[:i] if not _FLAT_VALUE.fullmatch(t)); items=[(name,labels[j],toks[i+j]) for j in range(len(labels)) if V.fullmatch(toks[i+j])]
        for name,p,v in items: seen[(c.ticker,name.lower(),p)][v.strip('$()').replace('$','')].add(c.doc_id)
multi={k:v for k,v in seen.items() if len({d for ds in v.values() for d in ds})>=2}
agree=sum(len(v)==1 for v in multi.values()); by=Counter(k[0] for k in multi); dis=Counter(k[0] for k,v in multi.items() if len(v)>1)
print('row x period seen in 2+ releases',len(multi),'agree',agree,f'{100*agree/len(multi):.1f}%'); print('by ticker',{t:f"{by[t]-dis[t]}/{by[t]}" for t in by})
for k,v in list((k,v) for k,v in multi.items() if len(v)>1)[:10]: print(k,{a:sorted(b)[:2] for a,b in v.items()})
print('--- rows with one value per release')
byd={}
for k,v in multi.items():
    d=defaultdict(set)
    for val,docs in v.items():
        for x in docs: d[x].add(val)
    if all(len(s)==1 for s in d.values()): byd[k]=d
ok=sum(len({next(iter(s)) for s in d.values()})==1 for d in byd.values())
print(len(byd),'agree',ok,f'{100*ok/len(byd):.2f}%')
by=Counter(k[0] for k in byd); dis=[(k,dict((x,next(iter(s))) for x,s in d.items())) for k,d in byd.items() if len({next(iter(s)) for s in d.values()})>1]
print({t:f"{by[t]-sum(k[0]==t for k,_ in dis)}/{by[t]}" for t in by})
for k,d in dis[:14]: print(k,{a.split('-EX')[0][-10:]:b for a,b in d.items()})
