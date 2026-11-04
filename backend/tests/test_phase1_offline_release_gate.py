"""Offline replay of real release-gate datasets/thresholds; synthetic external boundaries.

Opt in with RUN_PHASE1_OFFLINE_GATE=1. This measures offline regressions, never
live accuracy or accountant approval. Dataset failures remain gate blockers.
"""
import importlib.util
import json
import os
import sys
from pathlib import Path
import pytest
from tests.offline_http_support import offline_http  # noqa: F401


@pytest.mark.skipif(os.getenv("RUN_PHASE1_OFFLINE_GATE") != "1", reason="Explicit offline release gate")
async def test_offline_release_gate(offline_http):
    backend=Path(__file__).resolve().parents[1]
    spec=importlib.util.spec_from_file_location("phase1_gate",backend/"scripts/release_gate.py")
    gate=importlib.util.module_from_spec(spec);sys.modules[spec.name]=gate;spec.loader.exec_module(gate)
    config=json.loads(gate.GATES.read_text())
    baseline=json.loads(gate.BASELINE.read_text())
    verdicts=[]
    contamination_cases=[]
    for name,dataset in gate.DATASETS.items():
        results=[]
        try:
            cases=gate.runner.load_cases(dataset)
        except Exception as exc:
            cases=[]
            results=[{"id":name+":dataset","category":"configuration","passed":False,
                      "failures":["error: dataset unavailable: "+type(exc).__name__]}]
        contamination_cases.extend(cases)
        for case in cases:
            offline_http.rate_storage.reset()
            history=[]
            cid=name+"-"+case["id"]
            for index,turn in enumerate(case.get("turns",[])):
                prev=await offline_http.ask(turn,case_id=cid+"-turn-"+str(index),conversation=cid,history=history,allow_http_error=True)
                history.extend([{"role":"user","content":turn},
                                {"role":"assistant","content":gate.runner._reply_text(prev.body)[:4000]}])
            current=await offline_http.ask(case["question"],case_id=cid,conversation=cid,history=history,allow_http_error=True)
            payload=dict(current.body)
            if current.trace["http_status"] != 200:
                payload["_http_error"]="HTTP "+str(current.trace["http_status"])
            payload["_tools_used"]=[a["payload"].get("tool") for a in current.trace["audit"] if a["event"] == "agent_tool_called"]
            failures=gate.runner.score(case,payload)
            from app.domains.evaluation.pipeline_metrics import measure
            metrics=measure(case,payload,failures)
            results.append({"id":case["id"],"category":case["category"],"passed":not failures,"failures":failures,"metrics":metrics})
        # Match the production judge's exact thresholds and accepted baseline.
        verdicts.append(gate.judge(name,results,config["sets"][name],baseline))
    blockers=sum(len(v["regressions"])+len(v["unevaluated"])+len(v["metric_failures"])+int(v["below_minimum"])+len(v["zero_tolerance_failures"]) for v in verdicts)
    leaks=gate.scan_contamination(contamination_cases, backend/"app")
    blockers += len(leaks)
    result={"contamination_findings": leaks, "scope":"offline synthetic transport, not live accuracy", "production":"NO-GO",
            "blockers":blockers,"verdicts":verdicts}
    path=Path(os.getenv("PHASE1_GATE_REPORT","/private/tmp/zoiko-phase1-evidence/offline-release-gate.json"))
    path.write_text(json.dumps(result,indent=2))
    assert blockers == 0, f"Offline release gate blocked: {blockers}; see {path}"
