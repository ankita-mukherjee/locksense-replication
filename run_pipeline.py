#!/usr/bin/env python3
"""
LockSense Pipeline Orchestrator
Runs Job 1 -> Job 2 (JMH) -> Job 3 in sequence and prints a commit-status summary.

Usage:
    python run_pipeline.py [java_dir]
    ANTHROPIC_API_KEY=sk-ant-... python run_pipeline.py lock_examples/

Job 2 modes (set via environment variable JOB2_MODE):
    local   (default) -- builds Maven JAR locally and runs java -jar
    docker            -- builds Docker image and runs inside container
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT     = Path(__file__).parent
JAVA_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "lock_examples"
JOB2_DIR = ROOT / "job2_validate"

CANDIDATES_JSON           = ROOT / "candidates.json"
VALIDATED_CANDIDATES_JSON = ROOT / "validated_candidates.json"
REMEDIATION_JSON          = ROOT / "remediation_results.json"
JMH_RAW_JSON              = ROOT / "jmh_raw.json"


def run(cmd, **kwargs):
    print(f"\n  $ {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        print(f"  !! Command exited with code {result.returncode}")
    return result


def header(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ─────────────────────────────────────────────────────────────────
# JOB 1 -- AST Detection
# ─────────────────────────────────────────────────────────────────

header("JOB 1 -- AST-Based Smell Detection")
r = run(
    [sys.executable, str(ROOT / "job1_detect.py"),
     str(JAVA_DIR), str(CANDIDATES_JSON)]
)
if r.returncode != 0:
    print("Job 1 failed. Aborting pipeline.")
    sys.exit(1)

with open(CANDIDATES_JSON) as f:
    candidates = json.load(f)

warn_count = sum(1 for c in candidates if 0.5 <= c["severity_score"] < 0.7)
fail_count = sum(1 for c in candidates if c["severity_score"] >= 0.7)
print(f"\n  Candidates: {len(candidates)}  |  WARN (>=0.5): {warn_count}  |  FAIL (>=0.7): {fail_count}")

gate1_status = "pass" if not candidates else ("warning" if warn_count and not fail_count else "failure")
print(f"  Gate 1 status: {gate1_status.upper()}")


# ─────────────────────────────────────────────────────────────────
# JOB 2 -- JMH Runtime Contention Validation
# ─────────────────────────────────────────────────────────────────

header("JOB 2 -- JMH Runtime Contention Validation")

JOB2_MODE = os.environ.get("JOB2_MODE", "local").lower()

if JOB2_MODE == "docker":
    # ── Docker mode ──────────────────────────────────────────────
    print("\n  [Docker mode] Building locksense-job2 image …")
    r = run([
        "docker", "build", "-t", "locksense-job2",
        "-f", str(JOB2_DIR / "Dockerfile"),
        str(JOB2_DIR),
    ])
    if r.returncode != 0:
        print("Docker build failed. Aborting Job 2.")
        sys.exit(1)

    print("\n  [Docker mode] Running JMH benchmarks inside container …")
    # Mount ROOT so the container writes jmh_raw.json there
    r = run([
        "docker", "run", "--rm",
        "-v", f"{ROOT}:/output",
        "locksense-job2",
    ])
    if r.returncode != 0:
        print("Docker run failed.")

    # Parse results with the Python helper
    r = run([
        sys.executable, str(ROOT / "job2_jmh_runner.py"),
        str(CANDIDATES_JSON),
        str(VALIDATED_CANDIDATES_JSON),
    ])

else:
    # ── Local mode (default) ─────────────────────────────────────
    print("\n  [Local mode] Building Maven project and running JMH …")
    r = run([
        sys.executable, str(ROOT / "job2_jmh_runner.py"),
        str(CANDIDATES_JSON),
        str(VALIDATED_CANDIDATES_JSON),
    ])
    if r.returncode not in (0, None):
        print("Job 2 failed. Check output above.")

with open(VALIDATED_CANDIDATES_JSON) as f:
    validated = json.load(f)

print(f"\n  Confirmed candidates: {len(validated)} / {len(candidates)}")
if validated:
    print()
    print(f"  {'Smell':<30} {'Method':<30} {'CF':>6}  {'Degradation':>12}")
    print(f"  {'-'*30} {'-'*30} {'-'*6}  {'-'*12}")
    for v in validated:
        m = v.get("jlm_metrics", {})
        print(f"  {v['smell_type']:<30} {v['class']+'.'+v['method']+'()':<30}"
              f" {m.get('contention_factor', 0):>6.1f}"
              f" {m.get('throughput_degradation_pct', 0):>11.1f}%")


# ─────────────────────────────────────────────────────────────────
# JOB 3 -- AI-Assisted Remediation
# ─────────────────────────────────────────────────────────────────

header("JOB 3 -- AI-Assisted Remediation")

api_key = os.environ.get("ANTHROPIC_API_KEY", "")
if not api_key:
    print("\n  NOTE: ANTHROPIC_API_KEY not set.")
    print("  Job 3 will generate template placeholders only.")
    print("  To get real AI diffs:  set ANTHROPIC_API_KEY=sk-ant-…")

r = run([
    sys.executable, str(ROOT / "job3_remediate.py"),
    str(VALIDATED_CANDIDATES_JSON),
    str(REMEDIATION_JSON),
    str(JAVA_DIR),
    str(JAVA_DIR),
])

if REMEDIATION_JSON.exists():
    with open(REMEDIATION_JSON) as f:
        remediations = json.load(f)
    compiled  = sum(1 for r in remediations if r.get("remediation_status") == "compilable")
    templated = sum(1 for r in remediations if r.get("remediation_status") == "template_only")
    print(f"\n  Remediations: {len(remediations)}  |  Compilable: {compiled}  |  Templates: {templated}")


# ─────────────────────────────────────────────────────────────────
# COMMIT STATUS SUMMARY
# ─────────────────────────────────────────────────────────────────

header("COMMIT STATUS SUMMARY")

confirmed_high = sum(1 for v in validated if v.get("severity_score", 0) >= 0.7)
confirmed_any  = len(validated)

if confirmed_any == 0:
    commit_status = "PASS -- no confirmed contention above threshold"
elif confirmed_high == 0 and 1 <= confirmed_any <= 3:
    commit_status = "WARNING -- confirmed contention findings (all severity < 0.7)"
else:
    commit_status = "FAILURE -- high-severity contention confirmed or > 3 findings"

print(f"\n  {commit_status}")
print(f"\n  Job 1 candidates     : {len(candidates)}")
print(f"  Job 2 confirmed      : {confirmed_any}")
print(f"  High severity (>=0.7) : {confirmed_high}")
print(f"\n  Artifacts:")
print(f"    candidates.json             -> {CANDIDATES_JSON}")
print(f"    jmh_raw.json                -> {JMH_RAW_JSON}")
print(f"    validated_candidates.json   -> {VALIDATED_CANDIDATES_JSON}")
print(f"    remediation_results.json    -> {REMEDIATION_JSON}")
print()
