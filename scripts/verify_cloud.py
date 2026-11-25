"""Verify the authorized Railway deployment without printing request credentials."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import time
import urllib.error
import urllib.request
import uuid

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="https://day14-agent-53c5ceff.up.railway.app")
    parser.add_argument("--deployment-id", required=True)
    args = parser.parse_args()
    key = dotenv_values(ROOT / "06-lab-complete/.env.cloud").get("AGENT_API_KEY")
    if not key:
        raise RuntimeError("Set AGENT_API_KEY in ignored 06-lab-complete/.env.cloud first")
    report = {"base_url": args.url, "deployment_id": args.deployment_id,
              "tested_utc": datetime.now(timezone.utc).isoformat(), "tests": {}}

    def request(route, payload=None, authenticated=False):
        headers = {"Content-Type": "application/json"}
        if authenticated:
            headers["X-API-Key"] = key
        req = urllib.request.Request(args.url + route, headers=headers,
            data=None if payload is None else json.dumps(payload).encode())
        try:
            response = urllib.request.urlopen(req, timeout=30)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            raw = response.read().decode()
            try:
                body = json.loads(raw)
            except ValueError:
                body = raw
            # Response headers only: request key is never stored.
            return {"status": response.status, "body": body, "headers": dict(response.headers)}

    tests = report["tests"]
    tests["health"] = request("/health")
    tests["ready"] = request("/ready")
    question = {"question": "What is deployment?"}
    tests["missing_key"] = request("/ask", question)
    session = str(uuid.uuid4())
    tests["valid_key"] = request("/ask", {**question, "session_id": session}, True)
    assert [tests[n]["status"] for n in ("health", "ready", "missing_key", "valid_key")] == [200, 200, 401, 200]
    assert tests["valid_key"]["body"]["storage"] == "redis"
    tests["history"] = request("/history/" + session, authenticated=True)
    assert tests["history"]["body"]["message_count"] == 2
    tests["chat"] = request("/chat", {"question": "Explain Docker", "session_id": session}, True)
    assert tests["chat"]["body"]["message_count"] == 4
    req = urllib.request.Request(args.url + "/ask/stream", method="POST",
        headers={"X-API-Key": key, "Content-Type": "application/json"},
        data=json.dumps({"question": "What is deployment?", "session_id": session}).encode())
    started = time.monotonic()
    with urllib.request.urlopen(req, timeout=30) as response:
        events = []
        for line in response:
            if line.startswith(b"data: "):
                events.append({"elapsed_ms": round((time.monotonic()-started)*1000, 2),
                               "data": json.loads(line[6:])})
        tests["stream"] = {"status": response.status, "headers": dict(response.headers), "events": events}
    assert len(events) > 1 and events[-1]["data"]["message_count"] == 6
    tests["history_after_stream"] = request("/history/" + session, authenticated=True)
    assert tests["history_after_stream"]["body"]["message_count"] == 6
    report["passed"] = True
    target = ROOT / "reports/part6_cloud_http.json"
    if target.exists():
        archive = ROOT / "reports/diagnostics/part6_cloud_initial.json"
        if not archive.exists():
            shutil.copy2(target, archive)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    text = "\n\n".join(f"{name}: {tests[name]['status']}\n" +
        json.dumps(tests[name]["body"], ensure_ascii=False) for name in ("health", "ready", "missing_key", "valid_key"))
    (ROOT / "reports/part6_cloud_http.txt").write_text(text + "\n", encoding="utf-8")
    print("Cloud PASS: health=200 ready=200 missing_key=401 valid_key=200; Redis history, chat and SSE verified.")


if __name__ == "__main__":
    main()
