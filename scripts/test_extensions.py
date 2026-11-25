"""Exercise real Redis history, SSE, shared limits and three replicas via Nginx."""
import concurrent.futures
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request
import uuid

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "06-lab-complete"
REPORTS = ROOT / "reports"
BASE = "http://127.0.0.1:18006"
KEY = dotenv_values(LAB / ".env")["AGENT_API_KEY"]
COMPOSE = ["docker", "compose", "-p", "k5-day14-final"]
ENV = dict(os.environ, HOST_PORT="18006")


def request(path, body=None, auth=True):
    headers = {"Content-Type": "application/json"}
    if auth: headers["X-API-Key"] = KEY
    req = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(), headers=headers)
    try: response = urllib.request.urlopen(req, timeout=10)
    except urllib.error.HTTPError as error: response = error
    with response:
        body = response.read().decode()
        try: body = json.loads(body)
        except ValueError: pass
        return {"status": response.status, "body": body,
                "served_by": response.headers.get("X-Served-By")}


def ready():
    for _ in range(160):
        try:
            if request("/ready")["status"] == 200: return
        except OSError: pass
        time.sleep(.2)
    raise RuntimeError("Extensions stack did not become ready")


def main():
    report = {"started_utc": datetime.now(timezone.utc).isoformat(), "tests": {}}
    try:
        with (REPORTS / "part6_extensions_compose.txt").open("w") as log:
            subprocess.run(COMPOSE + ["up", "-d", "--build", "--scale", "agent=3"],
                           cwd=LAB, env=ENV, check=True, stdout=log, stderr=subprocess.STDOUT)
        ready()
        report["tests"]["health"] = request("/health", auth=False)
        report["tests"]["missing_key"] = request("/ask", {"question": "hello"}, False)
        report["tests"]["blank_question"] = request("/ask", {"question": "   "})
        assert report["tests"]["missing_key"]["status"] == 401
        assert report["tests"]["blank_question"]["status"] == 422
        session = str(uuid.uuid4())
        chats = [request("/chat", {"question": f"deployment question {i}", "session_id": session}) for i in range(3)]
        assert all(chat["status"] == 200 for chat in chats)
        backends = {chat["body"]["served_by"] for chat in chats}
        # Extra read-only requests observe rotation without spending request quota.
        for _ in range(6): backends.add(request("/history/" + session)["body"]["served_by"])
        assert len(backends) == 3, backends
        report["tests"]["three_backends"] = sorted(backends)
        report["tests"]["chat"] = chats
        history = request("/history/" + session)
        assert history["body"]["message_count"] == 6
        report["tests"]["shared_history"] = history
        req = urllib.request.Request(BASE + "/ask/stream",
            data=json.dumps({"question": "stream deployment", "session_id": session}).encode(),
            headers={"X-API-Key": KEY, "Content-Type": "application/json"})
        began = time.monotonic()
        events = []
        with urllib.request.urlopen(req, timeout=10) as response:
            assert response.status == 200
            assert response.headers.get_content_type() == "text/event-stream"
            for line in response:
                if line.startswith(b"data: "):
                    events.append({"elapsed_ms": round((time.monotonic()-began)*1000, 2),
                                   "data": json.loads(line[6:])})
        assert len(events) > 1 and events[0]["elapsed_ms"] < events[-1]["elapsed_ms"]
        assert events[-1]["data"]["session_id"] == session
        assert request("/history/" + session)["body"]["message_count"] == 8
        report["tests"]["stream_events"] = events
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            bursts = list(pool.map(lambda _: request("/ask", {"question": "rate test"}), range(10)))
        statuses = [item["status"] for item in bursts]
        assert statuses.count(200) == 6 and statuses.count(429) == 4, statuses
        report["tests"]["shared_rate_limit_burst_statuses"] = statuses
        subprocess.run(COMPOSE + ["restart", "agent"], cwd=LAB, env=ENV, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ready()
        history = request("/history/" + session)
        assert history["body"]["message_count"] == 8
        # Burst requests use their own sessions; the original conversation stays eight messages.
        report["tests"]["history_after_agent_restart"] = history
        assert request("/ask", {"question": "still limited"})["status"] == 429
        report["tests"]["rate_limit_after_restart"] = 429
        report["result"] = "PASS"
    finally:
        result = subprocess.run(COMPOSE + ["down"], cwd=LAB, env=ENV,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        report["cleanup_exit_code"] = result.returncode
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        (REPORTS / "part6_extensions_smoke.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"result":report.get("result"),"backends":report["tests"].get("three_backends"),
                      "stream_events":len(report["tests"].get("stream_events",[]))},indent=2))


if __name__ == "__main__":
    main()
