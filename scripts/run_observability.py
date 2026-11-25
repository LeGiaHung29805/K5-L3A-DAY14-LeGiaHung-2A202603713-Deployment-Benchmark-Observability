"""Reproduce Part 7 Docker measurements and fault-injection evidence in WSL.

Only operates the named lab Compose project. Does not stop unrelated services.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "06-lab-complete/benchmark-observability/production"
REPORTS = ROOT / "reports"
COMPOSE = ["docker", "compose", "-p", "k5-day14-observability"]


def now():
    return datetime.now(timezone.utc).isoformat()


def write(name, value):
    (REPORTS / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def http(url, payload=None, authenticated=False):
    headers = {"Content-Type": "application/json"}
    if authenticated:
        headers["X-API-Key"] = "day14-lab-key"
    req = urllib.request.Request(url, data=None if payload is None else json.dumps(payload).encode(), headers=headers)
    try:
        response = urllib.request.urlopen(req, timeout=15)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        body = response.read().decode()
        try: body = json.loads(body)
        except ValueError: pass
        return {"status": response.status, "headers": dict(response.headers), "body": body}


def compose(args, env=None, name="part7_compose_operations.txt"):
    with (REPORTS / name).open("a") as log:
        result = subprocess.run(COMPOSE + args, cwd=PROD, env=env, text=True,
                                stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"Compose failed: {args}; see {name}")


def ready():
    for _ in range(120):
        try:
            if http("http://127.0.0.1:8080/health")["status"] == 200:
                return
        except OSError:
            pass
        time.sleep(.5)
    raise RuntimeError("Nginx/agent not ready")


def locust(label, users, duration):
    args = COMPOSE + ["run", "--rm", "--no-deps", "locust", "-f", "/mnt/locust/locustfile.py",
                      "--host", "http://nginx", "--headless", "-u", str(users), "-r", "10",
                      "-t", f"{duration}s", "--csv", f"/mnt/results/{label}"]
    log = (REPORTS / f"part7_{label}_locust.txt").open("w")
    return subprocess.Popen(args, cwd=PROD, stdout=log, stderr=subprocess.STDOUT), log


def copy_csv():
    target = ROOT / "benchmark-results"
    target.mkdir(exist_ok=True)
    for path in (PROD / "benchmark-results").glob("*.csv"):
        shutil.copy2(path, target / path.name)


def baseline():
    compose(["up", "-d", "--scale", "agent=1"])
    ready()
    # Nginx's DNS cache can retain removed replicas for up to ten seconds.
    time.sleep(12)
    checks = {}
    for route in ("/health", "/ready", "/metrics"):
        checks[route] = http("http://127.0.0.1:8080" + route)
    checks["missing_key"] = http("http://127.0.0.1:8080/ask", {"question": "Hello"})
    checks["valid_key"] = http("http://127.0.0.1:8080/ask", {"question": "Explain tracing"}, True)
    attempts = [checks["valid_key"]]
    for _ in range(2):
        if checks["valid_key"]["status"] != 503: break
        checks["valid_key"] = http("http://127.0.0.1:8080/ask", {"question": "Explain tracing"}, True)
        attempts.append(checks["valid_key"])
    checks["valid_key_attempts"] = attempts
    write("part7_stack_smoke.json", checks)
    assert [checks[key]["status"] for key in ("/health", "/ready", "/metrics", "missing_key", "valid_key")] == [200, 200, 404, 401, 200]
    result = subprocess.run(["docker", "run", "--rm", "--entrypoint", "promtool", "-w", "/p",
                             "-v", str(PROD / "prometheus") + ":/p:ro", "prom/prometheus:v3.16.0",
                             "test", "rules", "/p/alert_rules_test.yml"], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (REPORTS / "part7_promtool.txt").write_text(result.stdout)
    assert result.returncode == 0, result.stdout
    runs = []
    for replicas in (1, 3):
        compose(["up", "-d", "--scale", f"agent={replicas}"])
        ready()
        ids = subprocess.check_output(COMPOSE + ["ps", "-q", "agent"], cwd=PROD, text=True).splitlines()
        assert len(ids) == replicas, ids
        observed = set()
        warmup_started = time.monotonic()
        while time.monotonic() - warmup_started < 45:
            item = http("http://127.0.0.1:8080/health")
            if item["status"] == 200:
                observed.add(item["body"]["instance"])
            if len(observed) == replicas and time.monotonic() - warmup_started >= 12:
                break
            time.sleep(.3)
        assert len(observed) == replicas, observed
        began = now()
        process, log = locust(f"scale_{replicas}", 100, 120)
        print(f"Locust scale_{replicas}: 100 users for 120 seconds", flush=True)
        code = process.wait()
        log.close()
        copy_csv()
        ids_after = subprocess.check_output(COMPOSE + ["ps", "-q", "agent"], cwd=PROD, text=True).splitlines()
        assert len(ids_after) == replicas, ids_after
        runs.append({"replicas": replicas, "started_utc": began, "exit_code": code,
                     "users": 100, "ramp_per_second": 10, "duration_seconds": 120,
                     "actual_containers_before": ids, "actual_containers_after": ids_after,
                     "observed_backend_ids": sorted(observed), "locust_no_deps": True})
        write("part7_scaling_manifest.json", runs)
        print(f"scale_{replicas} complete, exit code {code}; CSV retained", flush=True)
    write("part7_targets.json", http("http://127.0.0.1:9090/api/v1/targets"))


def experiment(name, duration, evidence_repeat=False):
    suffix = "_repeat" if evidence_repeat else ""
    changes = {
        "A": {"MOCK_ERROR_RATE": "0.2"},
        "B": {"MOCK_SLOW_RATE": "0.3"},
        "C": {"LLM_MODEL": "mock-llm-large"},
        "D": {},
        "E": {"AGENT_VERSION": "v1"},
        "AB": {"MOCK_ERROR_RATE": "0.2", "MOCK_SLOW_RATE": "0.3"},
    }[name]
    env = dict(os.environ, AGENT_VERSION="v2", LLM_MODEL="mock-llm-small",
               MOCK_ERROR_RATE="0.01", MOCK_SLOW_RATE="0.03", MOCK_LATENCY_MS="120")
    env.update(changes)
    record = {"experiment": name, "changed_at_utc": now(), "changes": changes,
              "load_users": 30, "duration_seconds": duration, "samples": [], "first_firing": {}}
    compose(["up", "-d", "--scale", "agent=3", "agent"], env=env)
    ready()
    record["actual_container_ids"] = subprocess.check_output(
        COMPOSE + ["ps", "-q", "agent"], cwd=PROD, text=True).splitlines()
    assert len(record["actual_container_ids"]) == 3
    if name == "E":
        import sys
        result = subprocess.run([sys.executable,
            str(ROOT / "06-lab-complete/benchmark-observability/develop/eval/run_eval.py"),
            "--url", "http://127.0.0.1:8080", "--api-key", "day14-lab-key", "--min-accuracy", "1.0",
            "--baseline", str(REPORTS / "eval_v2_fixed.json"), "--out", str(REPORTS / f"eval_production_v1{suffix}.json")],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (REPORTS / f"eval_production_v1{suffix}.txt").write_text(result.stdout)
        record["production_quality_gate_exit_code"] = result.returncode
    # Fresh Prometheus history per isolated experiment; save every sample to JSON.
    compose(["up", "-d", "--force-recreate", "--renew-anon-volumes", "prometheus"])
    for _ in range(60):
        try:
            if http("http://127.0.0.1:9090/-/ready")["status"] == 200: break
        except OSError: pass
        time.sleep(.5)
    paused = None
    if name == "D":
        paused = subprocess.check_output(COMPOSE + ["ps", "-q", "agent"], cwd=PROD, text=True).splitlines()[0]
        subprocess.run(["docker", "pause", paused], check=True, stdout=subprocess.DEVNULL)
    process, log = locust(f"experiment_{name}{suffix}", 30, duration)
    began = time.monotonic()
    record["load_started_utc"] = now()
    record["setup_seconds"] = round((datetime.fromisoformat(record["load_started_utc"]) -
                                     datetime.fromisoformat(record["changed_at_utc"])).total_seconds(), 2)
    print(f"Experiment {name}: {changes}, monitoring alerts for {duration}s", flush=True)
    try:
        while process.poll() is None:
            elapsed = round(time.monotonic() - began, 1)
            try:
                result = http("http://127.0.0.1:9090/api/v1/alerts")["body"]
                alerts = result["data"]["alerts"]
                record["samples"].append({"elapsed_seconds": elapsed, "observed_utc": now(), "alerts": alerts})
                for alert in alerts:
                    alertname = alert["labels"]["alertname"]
                    if alert["state"] == "firing" and alertname not in record["first_firing"]:
                        record["first_firing"][alertname] = elapsed
                        print(f"{name}: {alertname} firing after {elapsed}s from load start", flush=True)
                write(f"part7_experiment_{name}{suffix}.json", record)
            except (OSError, KeyError, ValueError) as error:
                record.setdefault("poll_errors", []).append(type(error).__name__)
            time.sleep(5)
        record["locust_exit_code"] = process.returncode
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=15)
        log.close()
        if paused:
            subprocess.run(["docker", "unpause", paused], check=True, stdout=subprocess.DEVNULL)
        record["finished_utc"] = now()
        copy_csv()
        write(f"part7_experiment_{name}{suffix}.json", record)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["baseline", "A", "B", "C", "D", "E", "AB"])
    parser.add_argument("--duration", type=int, default=190)
    parser.add_argument("--evidence-repeat", action="store_true", help="Keep primary measurements and write separate repeat evidence")
    args = parser.parse_args()
    REPORTS.mkdir(exist_ok=True)
    baseline() if args.phase == "baseline" else experiment(args.phase, args.duration, args.evidence_repeat)
