"""Verify Exercise 7.1 against a real, privately owned develop server process."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "06-lab-complete/benchmark-observability/develop"


def main():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    env = dict(os.environ, PORT=str(port), AGENT_VERSION="v2", MOCK_ERROR_RATE="0", MOCK_SLOW_RATE="0")
    with (ROOT / "reports/part7_question_metric_server.log").open("w") as log:
        process = subprocess.Popen([sys.executable, "app.py"], cwd=DEV, env=env,
                                   stdout=log, stderr=subprocess.STDOUT)
        try:
            for _ in range(100):
                try:
                    with urllib.request.urlopen(base + "/health", timeout=1):
                        break
                except OSError:
                    time.sleep(.1)
            question = "Prometheus thu thập metrics như thế nào?"
            req = urllib.request.Request(base + "/ask", data=json.dumps({"question": question}).encode(),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as response:
                assert response.status == 200
                answer = json.load(response)
            for route in ("/wp-admin", "/.env", "/a1b2c3"):
                try:
                    urllib.request.urlopen(base + route)
                except urllib.error.HTTPError as error:
                    assert error.code == 404
            with urllib.request.urlopen(base + "/metrics") as response:
                metrics = response.read().decode()
            from prometheus_client.parser import text_string_to_metric_families
            samples = {sample.name + json.dumps(sample.labels, sort_keys=True): sample.value
                       for family in text_string_to_metric_families(metrics) for sample in family.samples}
            count = samples['agent_question_length_chars_count{}']
            total = samples['agent_question_length_chars_sum{}']
            unmatched = samples['http_requests_total' + json.dumps(
                {"method": "GET", "route": "unmatched", "status": "404"}, sort_keys=True)]
            assert count == 1 and total == len(question) and unmatched == 3
            assert not any('route="' + route + '"' in metrics for route in ("/wp-admin", "/.env", "/a1b2c3"))
            report = {"result": "PASS", "question_length_chars": len(question),
                      "histogram_count": count, "histogram_sum": total,
                      "unmatched_404_count": unmatched, "answer_usage": answer["usage"]}
            (ROOT / "reports/part7_question_metrics.prom").write_text(metrics, encoding="utf-8")
        finally:
            process.send_signal(signal.SIGTERM)
            process.wait(timeout=10)
        report["server_exit_code"] = process.returncode
        report["application_shutdown_complete"] = "Application shutdown complete" in (
            ROOT / "reports/part7_question_metric_server.log").read_text(encoding="utf-8")
        # This test checks metrics, not the Part 6 graceful-shutdown contract.
        # Uvicorn's direct-run launcher can propagate SIGTERM after cleanup.
        assert report["application_shutdown_complete"]
        (ROOT / "reports/part7_question_metrics.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report))


if __name__ == "__main__":
    main()
