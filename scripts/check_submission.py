"""Audit K5 submission artifacts; preserve source reports and never expose secrets."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]
GIT = ["git", "-c", "safe.directory=" + ROOT.as_posix()]


def git(*args):
    return subprocess.check_output(GIT + list(args), cwd=ROOT)


def main():
    required = ["MISSION_ANSWERS.md", "DEPLOYMENT.md", "BENCHMARK_REPORT.md",
                "reports/part6_public_check.txt", "reports/part6_cloud_http.json",
                "reports/part6_extensions_smoke.json", "reports/part6_extensions_tests.txt",
                "reports/part7_trace_analysis.json", "reports/ci_quality_gate.json"]
    required += [f"reports/load_v2_c{number}.json" for number in (1, 10, 50, 100)]
    required += [f"reports/load_v2_slow_{rate}.json" for rate in ("0", "0.03", "0.1")]
    required += [f"reports/eval_{name}.json" for name in ("v1", "v2", "v2_fixed")]
    required += [f"benchmark-results/scale_{number}_stats.csv" for number in (1, 3)]
    images = ["dashboard", "running", "test", "grafana-dashboard", "jaeger-slow-trace",
              "jaeger-error-trace", "prometheus-alert-firing"]
    required += [f"screenshots/{name}.png" for name in images]
    assert all((ROOT / name).is_file() and (ROOT / name).stat().st_size for name in required)
    tracked = set(git("ls-files").decode().splitlines())
    assert set(required) <= tracked, "Required artifact exists locally but is not tracked by Git"
    image_sizes = {}
    for name in images:
        raw = (ROOT / f"screenshots/{name}.png").read_bytes()
        assert raw.startswith(b"\x89PNG\r\n\x1a\n"), name
        size = struct.unpack(">II", raw[16:24])
        assert min(size) >= 600, (name, size)
        image_sizes[name] = size
    protected = ["06-lab-complete/check_production_ready.py",
                 "06-lab-complete/benchmark-observability/develop/eval/golden_dataset.jsonl"]
    hashes = {}
    for name in protected:
        original = git("show", "83e677f:" + name)
        current = (ROOT / name).read_bytes()
        # Working-tree checkout may use CRLF; compare logical source byte-for-byte.
        assert original.replace(b"\r\n", b"\n") == current.replace(b"\r\n", b"\n"), name
        hashes[name] = hashlib.sha256(current).hexdigest()
    reports = ROOT / "reports"
    def read(name):
        return json.loads((reports / name).read_text(encoding="utf-8-sig"))
    assert "44/44 checks passed" in (reports / "part6_public_check.txt").read_text(encoding="utf-8")
    cloud = read("part6_cloud_http.json")
    assert cloud["passed"] and [cloud["tests"][name]["status"] for name in
        ("health", "ready", "missing_key", "valid_key")] == [200, 200, 401, 200]
    assert read("part6_extensions_smoke.json")["result"] == "PASS"
    fixed = read("eval_v2_fixed.json")
    assert fixed["total"] == fixed["passed"] == 23 and fixed["quality_gate"]["passed"]
    assert read("ci_quality_gate.json")["conclusion"] == "success"
    for number in (1, 3):
        name = f"scale_{number}_stats.csv"
        assert (ROOT / "benchmark-results" / name).read_bytes() == (ROOT /
            "06-lab-complete/benchmark-observability/production/benchmark-results" / name).read_bytes()
    manifest = read("part7_scaling_manifest.json")
    assert [len(run["actual_containers_before"]) for run in manifest] == [1, 3]
    assert [len(run["actual_containers_after"]) for run in manifest] == [1, 3]
    secrets = []
    for name in ("06-lab-complete/.env", "06-lab-complete/.env.cloud"):
        path = ROOT / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if line.startswith("AGENT_API_KEY="):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                if len(value) > 15:
                    secrets.append(value.encode())
    names = git("ls-files", "--cached", "--others", "--exclude-standard", "-z").decode().split("\0")
    leaked = []
    for name in names:
        path = ROOT / name
        if not name or not path.is_file() or path.suffix.lower() in (".png", ".jpg"):
            continue
        raw = path.read_bytes()
        if any(secret in raw for secret in secrets):
            leaked.append(name)
        assert not re.search(rb"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})", raw), name
    assert not leaked, leaked
    env_history = git("log", "--all", "--oneline", "--", "*.env", ".env").decode().strip()
    assert not env_history, "Environment file found in Git history"
    broken = []
    for name in ("MISSION_ANSWERS.md", "DEPLOYMENT.md", "BENCHMARK_REPORT.md"):
        path = ROOT / name
        for link in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8-sig")):
            if "://" not in link and not link.startswith("#") and not (path.parent / link.split("#")[0]).exists():
                broken.append([name, link])
    assert not broken, broken
    audit = {"checked_utc": datetime.now(timezone.utc).isoformat(), "result": "PASS",
             "required_artifacts": required, "image_dimensions": image_sizes,
             "required_artifacts_tracked_by_git": True,
             "protected_source_sha256": hashes, "protected_source_matches_original": True,
             "private_key_matches": leaked, "env_file_history_empty": True,
             "scaling_replica_counts": [1, 3], "cloud_http_statuses": [200, 200, 401, 200],
             "quality_eval": "23/23", "github_ci": "success", "broken_report_links": broken}
    (reports / "submission_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PASS: required artifacts, PNG encoding, protected source, cloud/CI/eval, replicas, links and secret checks.")


if __name__ == "__main__":
    main()
