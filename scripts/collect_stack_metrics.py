"""Exercise 7.4: two replicas, 30 users, ramp 5/s, and actual PromQL readings."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.parse

from run_observability import COMPOSE, PROD, REPORTS, compose, copy_csv, http, ready


def main():
    env = dict(os.environ, AGENT_VERSION="v2", LLM_MODEL="mock-llm-small",
               MOCK_ERROR_RATE="0.01", MOCK_SLOW_RATE="0.03", MOCK_LATENCY_MS="120")
    compose(["up", "-d", "--scale", "agent=2", "agent"], env=env)
    ready()
    time.sleep(15)
    ids = subprocess.check_output(COMPOSE + ["ps", "-q", "agent"], cwd=PROD, text=True).splitlines()
    assert len(ids) == 2
    args = COMPOSE + ["run", "--rm", "--no-deps", "locust", "-f", "/mnt/locust/locustfile.py",
        "--host", "http://nginx", "--headless", "-u", "30", "-r", "5", "-t", "120s",
        "--csv", "/mnt/results/exercise_7_4"]
    with (REPORTS / "part7_exercise_7_4_locust.txt").open("w") as log:
        process = subprocess.Popen(args, cwd=PROD, stdout=log, stderr=subprocess.STDOUT)
        try:
            # Wait beyond the one-minute metric window; leave 45s for a UI capture.
            time.sleep(75)
            queries = {
                "avg_seconds": 'sum(rate(http_request_duration_seconds_sum{job="agent",route="/ask"}[1m])) / sum(rate(http_request_duration_seconds_count{job="agent",route="/ask"}[1m]))',
                "p95_seconds": 'histogram_quantile(0.95,sum by(le)(rate(http_request_duration_seconds_bucket{job="agent",route="/ask"}[1m])))',
                "rps_by_instance": 'sum by(instance)(rate(http_requests_total{job="agent",route="/ask"}[1m]))',
                "tokens_per_second": 'sum by(type)(rate(llm_tokens_total{job="agent"}[1m]))',
                "question_histogram_count": 'sum(agent_question_length_chars_count{job="agent"})',
            }
            record = {"observed_utc": datetime.now(timezone.utc).isoformat(), "replicas": 2,
                      "users": 30, "ramp_per_second": 5, "duration_seconds": 120,
                      "container_ids": ids, "queries": {}}
            for name, expression in queries.items():
                response = http("http://127.0.0.1:9090/api/v1/query?" + urllib.parse.urlencode({"query": expression}))
                assert response["status"] == 200
                record["queries"][name] = {"expression": expression, "response": response["body"]}
            (REPORTS / "part7_exercise_7_4_metrics.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
            print("PromQL readings saved; two replicas still under 30-user load for the screenshot.", flush=True)
            record["locust_exit_code"] = process.wait()
            copy_csv()
            (REPORTS / "part7_exercise_7_4_metrics.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=15)


if __name__ == "__main__":
    main()
