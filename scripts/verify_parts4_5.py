"""Collect real HTTP evidence for earlier exercises without exposing credentials."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
PROCESSES = []
TRANSCRIPT = []


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def http(base, path, payload=None, headers=None, record=True):
    req = urllib.request.Request(base + path,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **(headers or {})})
    try: response = urllib.request.urlopen(req, timeout=10)
    except urllib.error.HTTPError as error: response = error
    with response:
        text = response.read().decode()
        body = json.loads(text)
        if record:
            TRANSCRIPT.append(f"{req.get_method()} {path}\nHTTP {response.status}\n" +
                              "\n".join(f"{key}: {value}" for key,value in response.headers.items()) +
                              "\n\n" + text + "\n")
        return response.status, dict(response.headers), body


def start(folder, label, direct=False, **extra):
    port = free_port()
    log = (REPORTS / f"{label}_server.log").open("w")
    command = [sys.executable,"app.py"] if direct else [sys.executable,"-m","uvicorn","app:app","--host","127.0.0.1",
                             "--port",str(port),"--timeout-graceful-shutdown","5"]
    proc = subprocess.Popen(command,
        cwd=ROOT/folder, env=dict(os.environ,PYTHONDONTWRITEBYTECODE="1",PORT=str(port),**extra),
        stdout=log,stderr=subprocess.STDOUT)
    PROCESSES.append((proc,log))
    base=f"http://127.0.0.1:{port}"
    for _ in range(100):
        if proc.poll() is not None: raise RuntimeError(f"Server exited: {label}")
        try:
            if http(base,"/health",record=False)[0] == 200: return proc,base
        except OSError: pass
        time.sleep(.1)
    raise RuntimeError(f"Startup timeout: {label}")


def main(part5_only=False):
    report={"started_utc":datetime.now(timezone.utc).isoformat(),"executed_by":"Codex, authorized completion run"}
    if part5_only:
        report=json.loads((REPORTS/"parts4_5_verification.json").read_text(encoding="utf-8"))
        report["part5_started_utc"]=datetime.now(timezone.utc).isoformat()
    try:
        if not part5_only:
            key=secrets.token_urlsafe(32)
            _,base=start("04-api-gateway/develop","part4_api_key",AGENT_API_KEY=key)
            codes=[http(base,"/ask",{"question":"Hello"})[0],
                   http(base,"/ask",{"question":"Hello"},{"X-API-Key":"incorrect"})[0],
                   http(base,"/ask",{"question":"Hello"},{"X-API-Key":key})[0]]
            assert codes == [401,403,200], codes
            report["api_key_statuses"]=codes
            _,base=start("04-api-gateway/production","part4_jwt",JWT_SECRET=secrets.token_urlsafe(48))
            token=http(base,"/auth/token",{"username":"student","password":"demo123"},record=False)[2]["access_token"]
            auth={"Authorization":"Bearer "+token}
            report["jwt_missing_status"]=http(base,"/ask",{"question":"Hello"})[0]
            before=http(base,"/me/usage",headers=auth)[2]
            codes=[http(base,"/ask",{"question":"Hello"},auth)[0]]
            after=http(base,"/me/usage",headers=auth)[2]
            assert after["requests"] == before["requests"]+1 and after["cost_usd"] > before["cost_usd"]
            report["usage_before"]=before
            report["usage_after"]=after
            for _ in range(10):
                status,headers,_=http(base,"/ask",{"question":"Hello"},auth)
                codes.append(status)
            assert codes == [200]*10+[429], codes
            report["jwt_and_rate_statuses"]=codes
            retry=int(next(value for key,value in headers.items() if key.lower()=="retry-after"))
            report["retry_after_seconds"]=retry
            print(f"Part 4: 401/403/200; JWT 401/200; request 11 is 429; waiting Retry-After={retry}s",flush=True)
            time.sleep(retry+1)
            report["after_retry_status"]=http(base,"/ask",{"question":"retry"},auth)[0]
            assert report["after_retry_status"] == 200
            (REPORTS/"part4_http_verification.txt").write_text("\n".join(TRANSCRIPT),encoding="utf-8")
        # The transcript includes only response headers/body, never token-issuing response or request auth headers.
        proc,base=start("05-scaling-reliability/develop","part5_health_shutdown",direct=True)
        p5={"health":http(base,"/health")[0],"ready":http(base,"/ready")[0]}
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending=pool.submit(http,base,"/ask?question=deployment",{})
            time.sleep(.05)
            began=time.monotonic()
            proc.terminate()
            p5["in_flight_request_status"]=pending.result(timeout=10)[0]
        p5["server_exit_code"]=proc.wait(timeout=10)
        p5["shutdown_seconds"]=round(time.monotonic()-began,3)
        assert [p5["health"],p5["ready"],p5["in_flight_request_status"]] == [200,200,200]
        report["part5"]=p5
        report["result"]="PASS"
    finally:
        for proc,log in PROCESSES:
            if proc.poll() is None:
                proc.terminate()
                try: proc.wait(timeout=10)
                except subprocess.TimeoutExpired: proc.kill();proc.wait()
            log.close()
        report["finished_utc"]=datetime.now(timezone.utc).isoformat()
        (REPORTS/"parts4_5_verification.json").write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps({"result":report.get("result"),"part5":report.get("part5")},indent=2))


if __name__ == "__main__": main("--part5-only" in sys.argv)
