"""The 14 table questions answered by the larger model (the evidence behind ANSWER_ROUTE_RELEASES).

Run from the repo root: PYTHONPATH=. python scripts/audits/table_questions_larger_model.py reports/table_questions_larger_model.json
New answers cost ~4k Groq tokens each; repeat runs come from the cache.
"""
import json
from app.agent.graph import FinRAGAgent
from app.agent.xbrl import XbrlStore
from app.config import get_settings
from app.evaluation.golden import load_golden
from app.generation.llm import build_llm
from app.retrieval.factory import build_retriever
s=get_settings(); big=build_llm(s.model_copy(update={"llm_providers":"groq"}))
a=FinRAGAgent(build_retriever(s),build_llm(s),xbrl=XbrlStore.from_settings(),token_budget=s.context_token_budget,routed_llm=big,routed_intents=("lookup","numeric","trend","comparison"))
ids=["E29"]+[f"E{i}" for i in range(34,47)]
qs={q.id:q for q in load_golden('data/eval/golden_earnings_v0.jsonl'.__class__ and __import__('pathlib').Path('data/eval/golden_earnings_v0.jsonl'))}
out=[]
for i in ids:
    q=qs[i]; t=a.run(q.question,q.history); r=t.result
    out.append({"id":i,"q":q.question,"ref":q.reference_answer,"answer":r.answer,"abstained":r.abstained,"reason":r.abstain_reason,"model":r.model,"confidence":r.confidence,"tokens":r.usage})
    print(i,r.model,'ABST' if r.abstained else 'ANS',(r.answer or r.abstain_reason)[:150],'| REF',q.reference_answer[:70],flush=True)
json.dump(out,open(__import__('sys').argv[1],'w'),indent=1)
