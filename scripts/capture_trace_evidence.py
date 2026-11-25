"""Export real Jaeger traces and matching app log lines; no synthetic data."""
import json
from pathlib import Path
import subprocess
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
PROD = ROOT / "06-lab-complete/benchmark-observability/production"


def fetch(**params):
    # Jaeger 2.23 searches through API v3; trace-by-ID still supports
    # the documented legacy response used by the analysis below.
    run=json.loads((REPORTS/"part7_experiment_AB.json").read_text(encoding="utf-8"))
    query={"query.service_name":"observable-agent",
           "query.start_time_min":run["load_started_utc"],
           "query.start_time_max":run["finished_utc"],
           "query.search_depth":100}
    if "minDuration" in params: query["query.duration_min"]=params["minDuration"]
    if "tags" in params: query["query.attributes"]=params["tags"]
    url="http://127.0.0.1:16686/api/v3/trace-summaries?"+urllib.parse.urlencode(query)
    with urllib.request.urlopen(url,timeout=30) as response:
        summaries=json.load(response).get("summaries",[])
    result=[]
    for summary in summaries:
        with urllib.request.urlopen("http://127.0.0.1:16686/api/traces/"+summary["traceId"],timeout=30) as response:
            result.extend(json.load(response)["data"])
    return result


def duration(trace):
    spans=trace["spans"]
    return max(span["startTime"]+span["duration"] for span in spans)-min(span["startTime"] for span in spans)


def main():
    slow=sorted(fetch(minDuration="1.5s"),key=duration,reverse=True)
    errors=fetch(tags=json.dumps({"error":"true"}))
    assert slow and errors, "Generate actual slow/error traffic first"
    selected={"slow":slow[0],"error":errors[0]}
    lines=subprocess.check_output(["docker","compose","-p","k5-day14-observability","logs",
        "--no-color","--since","30m","agent"],cwd=PROD,text=True)
    records=[]
    wanted={trace["traceID"] for trace in selected.values()}
    for line in lines.splitlines():
        try: item=json.loads(line[line.index('{'):])
        except (ValueError,json.JSONDecodeError): continue
        if item.get("trace_id") in wanted: records.append(item)
    analysis={}
    for label,trace in selected.items():
        llm=max((span for span in trace["spans"] if span["operationName"].startswith("chat ")),
                key=lambda span:span["duration"])
        analysis[label]={"trace_id":trace["traceID"],"total_ms":round(duration(trace)/1000,3),
            "llm_span":llm["operationName"],"llm_ms":round(llm["duration"]/1000,3),
            "llm_share_percent":round(llm["duration"]/duration(trace)*100,2),
            "span_count":len(trace["spans"]),"exception_events":[entry for entry in llm.get("logs",[])
                if any(field.get("value")=="exception" for field in entry.get("fields",[]))],
            "matching_logs":[item for item in records if item.get("trace_id")==trace["traceID"]]}
        (REPORTS/f"jaeger_{label}_trace.json").write_text(json.dumps(trace,indent=2,ensure_ascii=False),encoding="utf-8")
    assert all(item["matching_logs"] for item in analysis.values()), "Missing log correlation"
    assert analysis["error"]["exception_events"], "Error trace must contain an actual exception event"
    (REPORTS/"part7_trace_analysis.json").write_text(json.dumps(analysis,indent=2,ensure_ascii=False),encoding="utf-8")
    (REPORTS/"part7_trace_logs.json").write_text(json.dumps(records,indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps({label:{k:v for k,v in item.items() if k not in ("matching_logs","exception_events")}
                      for label,item in analysis.items()},indent=2))


if __name__ == "__main__": main()
