"""Temporary calibration diagnostic — dumps per-case detail for tuning. Not a test."""
import sys, json, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import harness, graders, judge
from agent import SupportAgent

CASES = json.loads((Path(__file__).resolve().parent / "golden_set.json").read_text("utf-8"))["cases"]
DIAG = Path(__file__).resolve().parent / "_diag.json"
a = SupportAgent()
out = []
# resume support: skip cases already in a previous partial _diag.json
if DIAG.exists():
    out = json.loads(DIAG.read_text("utf-8"))
    done_ids = {r["id"] for r in out}
    CASES = [c for c in CASES if c["id"] not in done_ids]
    print(f"resuming — {len(done_ids)} cases already saved, {len(CASES)} to go")
for c in CASES:
    try:
        r = harness.run_case(a, c)
    except Exception as e:
        print(f"\n=== {c['id']}  ERROR: {e}")
        break
    pages = [(x.get("page_number"), x.get("doc_slug")) for x in r.retrieval_trace]
    recall = graders.retrieval_recall(
        r.retrieval_trace, c["expected_pages"], c.get("expected_doc_slug", "manual"),
        mode=c.get("recall_mode", "all"),
    )
    faith = None
    if c.get("faithfulness"):
        faith = judge.judge_faithfulness(a._claude, judge.judge_model(), c["query"], r.text_blob, r.retrieval_trace)
    rec = {
        "id": c["id"], "exp_route": c["expected_route"], "got_route": r.route,
        "exp_pages": c["expected_pages"], "exp_slug": c.get("expected_doc_slug", "manual"),
        "got_pages": pages, "recall": round(recall, 2),
        "answer": (r.answer or "")[:280],
        "faith": (faith["passed"] if faith else None),
        "faith_reason": (faith["reason"][:200] if faith else ""),
    }
    out.append(rec)
    DIAG.write_text(json.dumps(out, indent=2), "utf-8")  # save after every case
    print(f"\n=== {rec['id']}  route {rec['exp_route']}->{rec['got_route']}  recall {rec['recall']}  faith {rec['faith']}")
    print(f"  exp_pages {rec['exp_pages']}({rec['exp_slug']})  got {rec['got_pages']}")
    if rec["answer"]:
        print(f"  ans: {re.sub(chr(10),' ',rec['answer'])}")
    if rec["faith_reason"]:
        print(f"  judge: {rec['faith_reason']}")
print(f"\nSaved _diag.json ({len(out)} cases)")
