"""Audit of the column check on real data. Run from the repo root: PYTHONPATH=. python scripts/audits/column_claims.py"""
import json,re
from collections import Counter,defaultdict
from app.config import get_settings
from app.generation.columns import known_periods,periods_of_figure,split_row,_chunk_headers,_FLAT_VALUE
from app.generation.verify import extract_numbers,_matches,_column_verdict
from app.ingestion.models import Chunk
s=get_settings()
rel=[Chunk(**json.loads(l)) for l in open(s.processed_dir/'chunks_earnings.jsonl',encoding='utf-8')]
tabs=[c for c in rel if c.chunk_type=='table']; read=[c for c in tabs if known_periods(c)]
print('tables',len(tabs),'columns readable',len(read),Counter(c.ticker for c in read))
right=Counter();wrong=Counter();badr=[];mis=[]
for c in read:
    for row in c.text.split('\n'):
        md,flat=_chunk_headers(c)
        cells=[]
        if md and row.startswith('|') and not row.startswith('|---'):
            cs=split_row(row)
            if len(cs)!=len(md): continue
            cells=[(cs[j],md[j]) for j in range(len(md)) if md[j] and cs[j] and re.fullmatch(r'\(?\$?\d[\d,]{3,}\)?',cs[j])]
        elif flat:
            labels,yoy=flat; toks=row.split(); w=len(labels)+yoy
            i=0
            while i<len(toks):
                if not _FLAT_VALUE.fullmatch(toks[i]): i+=1; continue
                e=i
                while e<len(toks) and _FLAT_VALUE.fullmatch(toks[e]): e+=1
                if e-i==w: cells+=[(toks[i+j],labels[j]) for j in range(len(labels)) if re.fullmatch(r'\(?\$?\d[\d,]{3,}\)?',toks[i+j])]
                i=e
        vals=[v for v,_ in cells]
        for v,(q,y) in cells:
            nums=extract_numbers(v.strip('()'))
            if not nums: continue
            n=nums[0]
            claim=f"The figure was {n.raw} in Q{q} FY{y}."
            v0=_column_verdict(n,claim,row,c); ok=v0 is not False; right[c.ticker,ok]+=1
            if not ok: badr.append((c.chunk_id,claim,row[:100]))
            for v2,(q2,y2) in cells:
                if (q2,y2)==(q,y) or v2==v: continue
                # a wrong-period claim, only when this figure isn't also in that column
                claim2=f"The figure was {n.raw} in Q{q2} FY{y2}."
                ok2=_column_verdict(n,claim2,row,c) is not False; wrong[c.ticker,ok2]+=1
                if ok2: mis.append((c.chunk_id,claim2,row[:100]))
tr=sum(v for k,v in right.items() if k[1]); fr=sum(v for k,v in right.items() if not k[1]); tw=sum(v for k,v in wrong.items() if not k[1]); fw=sum(v for k,v in wrong.items() if k[1])
print(f'right-column claims accepted {tr}/{tr+fr}; wrong-column claims rejected {tw}/{tw+fw}')
print('false rejects',badr[:6]); print('missed',mis[:6])
