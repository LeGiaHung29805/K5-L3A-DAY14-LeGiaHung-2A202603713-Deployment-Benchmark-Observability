"""Run real Part 7 benchmarks; retain JSON, logs, configuration and exit codes.

Use the lab venv in WSL. Baseline must run before fixing the knowledge base.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "06-lab-complete/benchmark-observability/develop"
REPORTS = ROOT / "reports"
REPORTS.mkdir(exist_ok=True)
PROCESSES = []
RUNS = []


def start(version, port, error="0", slow="0.03"):
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", port))
    env = dict(os.environ, AGENT_VERSION=version, PORT=str(port),
               MOCK_ERROR_RATE=error, MOCK_SLOW_RATE=slow, PYTHONDONTWRITEBYTECODE="1")
    log = (REPORTS / f"part7_{version}_{port}_error{error}_slow{slow}.log").open("a")
    proc = subprocess.Popen([sys.executable, "app.py"], cwd=DEV, env=env,
                            stdout=log, stderr=subprocess.STDOUT)
    PROCESSES.append((proc, log))
    for _ in range(100):
        if proc.poll() is not None:
            raise RuntimeError(f"Agent exited: {proc.returncode}; see {log.name}")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                if response.status == 200:
                    return proc, log
        except OSError:
            time.sleep(.1)
    raise RuntimeError("Agent startup timed out")


def stop(pair):
    proc, log = pair
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    log.close()


def run(script, port, name, *extra):
    output = REPORTS / name
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite evidence: {output}")
    args = [sys.executable, script, "--url", f"http://127.0.0.1:{port}",
            "--out", str(output), *extra]
    began = datetime.now(timezone.utc).isoformat()
    with output.with_suffix(".txt").open("w") as log:
        result = subprocess.run(args, cwd=DEV, stdout=log, stderr=subprocess.STDOUT)
    if not output.exists():
        raise RuntimeError(f"No JSON produced: {name}; inspect text log")
    mirror = DEV / "reports" / name
    mirror.parent.mkdir(exist_ok=True)
    shutil.copy2(output, mirror)
    RUNS.append({"command": args[1:], "started_utc": began, "exit_code": result.returncode})
    report = json.loads(output.read_text())
    print(json.dumps({"file": name, "exit_code": result.returncode,
                      "accuracy": report.get("accuracy"), "rps": report.get("rps"),
                      "latency_ms": report.get("latency_ms")}), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["baseline", "slow", "fixed"])
    args = parser.parse_args()
    try:
        if args.phase == "baseline":
            v1 = start("v1", 8001)
            v2 = start("v2", 8002)
            # Isolate knowledge quality from random upstream failures in all evals.
            run("eval/run_eval.py", 8001, "eval_v1.json")
            run("eval/run_eval.py", 8002, "eval_v2.json", "--baseline", str(REPORTS / "eval_v1.json"))
            run("eval/run_eval.py", 8001, "eval_v1_regression.json", "--baseline", str(REPORTS / "eval_v2.json"))
            stop(v1)
            stop(v2)
            v2 = start("v2", 8002, error="0.01")
            for concurrency in (1, 10, 50, 100):
                run("load_test.py", 8002, f"load_v2_c{concurrency}.json",
                    "--requests", "300", "--concurrency", str(concurrency))
            stop(v2)
        if args.phase in ("baseline", "slow"):
            for slow in ("0", "0.03", "0.1"):
                v2 = start("v2", 8002, error="0.01", slow=slow)
                run("load_test.py", 8002, f"load_v2_slow_{slow}.json",
                    "--requests", "300", "--concurrency", "20")
                stop(v2)
        if args.phase == "fixed":
            v2 = start("v2", 8002)
            report = run("eval/run_eval.py", 8002, "eval_v2_fixed.json", "--min-accuracy", "1.0",
                         "--baseline", str(REPORTS / "eval_v2.json"))
            if not report["quality_gate"]["passed"]:
                raise RuntimeError("Fixed knowledge base did not pass quality gate")
    finally:
        for pair in PROCESSES:
            if not pair[1].closed:
                stop(pair)
        metadata = {"phase": args.phase, "recorded_utc": datetime.now(timezone.utc).isoformat(),
                    "python": platform.python_version(), "platform": platform.platform(),
                    "logical_cpus": os.cpu_count(), "runs": RUNS,
                    "eval_configuration": {"MOCK_ERROR_RATE": "0", "MOCK_SLOW_RATE": "0.03"},
                    "load_configuration": {"MOCK_ERROR_RATE": "0.01", "MOCK_SLOW_RATE": "0.03 except slow comparison"}}
        (REPORTS / f"part7_local_{args.phase}_manifest.json").write_text(
            json.dumps(metadata, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
