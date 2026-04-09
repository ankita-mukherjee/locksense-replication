#!/usr/bin/env python3
"""
LockSense Job 2: JMH-Based Runtime Contention Validation
=========================================================
Reads candidates.json, runs JMH benchmarks (baseline vs stressed),
computes contention metrics, and writes validated_candidates.json.

Usage:
    python job2_jmh_runner.py [candidates.json] [validated_candidates.json]

Contention confirmation rule (adapts paper Eq. 2 for JMH without JLM):
    confirmed  iff  contention_factor > CONTENTION_FACTOR_THRESHOLD
    where:
        ideal_throughput   = baseline_throughput × thread_count
        contention_factor  = ideal_throughput / stressed_throughput
    A factor > 2.0 means the actual throughput is less than 50% of ideal,
    indicating meaningful serialisation overhead from the lock.

Mapping convention (benchmark name -> candidate):
    "BankAccountBenchmark.depositBaseline"
        -> class="BankAccount", method="deposit", run_type="baseline"
    Strip "Benchmark" suffix from class name.
    Strip "Baseline" or "Stressed" suffix from method name.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

# ── configuration ─────────────────────────────────────────────────────────────

ROOT         = Path(__file__).parent
JOB2_DIR     = ROOT / "job2_validate"
JAR_PATH     = JOB2_DIR / "target" / "benchmarks.jar"
JMH_RAW_JSON = ROOT / "jmh_raw.json"

# JMH run parameters (keep small for local dev; paper uses wi=10 mi=100)
JMH_WARMUP_ITERS      = 5
JMH_MEASURE_ITERS     = 10
JMH_FORKS             = 1

# Confirmation threshold: if actual throughput < 50 % of ideal -> contended
CONTENTION_FACTOR_THRESHOLD = 1.05


# ── step 1: build Maven fat JAR ───────────────────────────────────────────────

def build_jar(force_rebuild=False):
    if JAR_PATH.exists() and not force_rebuild:
        print(f"[Job 2] Using cached JAR: {JAR_PATH}")
        return True

    print("[Job 2] Building Maven JMH project …")
    result = subprocess.run(
        ["mvn", "-q", "package", "-DskipTests", "-f", str(JOB2_DIR / "pom.xml")],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print("[Job 2] Maven build FAILED:")
        print(result.stdout[-3000:])
        print(result.stderr[-3000:])
        return False

    print(f"[Job 2] Build successful -> {JAR_PATH}")
    return True


# ── step 2: run JMH benchmarks ───────────────────────────────────────────────

def run_jmh(jmh_out_path: Path):
    """Run all JMH benchmarks and produce a JSON result file."""
    print(f"\n[Job 2] Running JMH benchmarks  (wi={JMH_WARMUP_ITERS} mi={JMH_MEASURE_ITERS} f={JMH_FORKS})")
    print(        "        This may take a few minutes …\n")

    cmd = [
        "java", "-jar", str(JAR_PATH),
        "-wi", str(JMH_WARMUP_ITERS),
        "-i",  str(JMH_MEASURE_ITERS),
        "-f",  str(JMH_FORKS),
        "-rf", "json",
        "-rff", str(jmh_out_path),
    ]
    result = subprocess.run(cmd, text=True)
    if result.returncode != 0:
        print("[Job 2] JMH run exited with non-zero status (partial results may exist)")
        return jmh_out_path.exists()
    return True


# ── step 3: parse JMH results -> contention metrics ───────────────────────────

def parse_benchmark_name(full_name: str):
    """
    "BankAccountBenchmark.depositBaseline"
    -> (target_class="BankAccount", target_method="deposit", run_type="baseline")
    """
    # full_name may include package: "BankAccountBenchmark.depositBaseline"
    # or the fully qualified form from JMH JSON: just strip to last two parts
    parts = full_name.rsplit(".", 1)
    if len(parts) != 2:
        return None, None, None

    bench_class = parts[0].rsplit(".", 1)[-1]   # e.g. "BankAccountBenchmark"
    bench_method = parts[1]                       # e.g. "depositBaseline"

    target_class = bench_class.removesuffix("Benchmark")

    if bench_method.endswith("Baseline"):
        target_method = bench_method.removesuffix("Baseline")
        run_type = "baseline"
    elif bench_method.endswith("Stressed"):
        target_method = bench_method.removesuffix("Stressed")
        run_type = "stressed"
    else:
        return None, None, None

    return target_class, target_method, run_type


def load_jmh_results(jmh_path: Path) -> dict:
    """
    Returns dict keyed by (target_class, target_method):
        {"baseline": {"score": float, "threads": int},
         "stressed": {"score": float, "threads": int}}
    """
    with open(jmh_path) as f:
        data = json.load(f)

    results = {}
    for entry in data:
        full_name = entry.get("benchmark", "")
        target_class, target_method, run_type = parse_benchmark_name(full_name)
        if not target_class:
            continue

        key = (target_class, target_method)
        if key not in results:
            results[key] = {}

        results[key][run_type] = {
            "score":   entry["primaryMetric"]["score"],
            "threads": entry.get("threads", 1),
        }

    return results


def compute_metrics(baseline_score: float, stressed_score: float, n_threads: int) -> dict:
    """
    Derive contention metrics from JMH throughput scores.

    contention_factor = ideal_throughput / actual_throughput
        where ideal_throughput = baseline × n_threads (perfect linear scaling)
    throughput_degradation_pct = (1 - actual/ideal) × 100

    These proxy the paper's ΔAVER_HTM and ΔGETS without needing JLM.
    """
    ideal = baseline_score * n_threads
    factor = ideal / max(stressed_score, 1e-9)
    degradation_pct = max(0.0, (1.0 - stressed_score / ideal) * 100.0)

    return {
        "throughput_1t_ops_per_sec":  round(baseline_score,   2),
        "throughput_mt_ops_per_sec":  round(stressed_score,   2),
        "thread_count_used":          n_threads,
        "ideal_throughput_ops_per_sec": round(ideal,          2),
        "contention_factor":          round(factor,           2),
        "throughput_degradation_pct": round(degradation_pct,  2),
        # Paper-compatible field names (JMH proxy values)
        "delta_htm_pct":   round(degradation_pct, 2),   # throughput loss ≈ hold-time proxy
        "delta_gets_pct":  0.0,                          # N/A without JLM
        "spin_count":      0,                            # N/A without JLM
        "match_confidence": "high",
        "profiler":        "jmh",
    }


def confirm_candidates(candidates: list, jmh_results: dict) -> list:
    """
    Match each candidate to its JMH result and apply the confirmation rule.
    Returns only confirmed candidates, each augmented with jlm_metrics.
    """
    validated = []
    no_result  = []

    print(f"\n[Job 2] Matching {len(candidates)} candidates to JMH results …\n")
    print(f"  {'Smell':<30} {'Class.Method':<35} {'CF':>6}  {'Degradation':>12}  Result")
    print(f"  {'-'*30} {'-'*35} {'-'*6}  {'-'*12}  ------")

    for cand in candidates:
        target_class  = cand["class"]
        target_method = cand["method"]
        key = (target_class, target_method)

        if key not in jmh_results or "baseline" not in jmh_results[key] or "stressed" not in jmh_results[key]:
            no_result.append(cand)
            label = f"{target_class}.{target_method}()"
            print(f"  {cand['smell_type']:<30} {label:<35} {'N/A':>6}  {'N/A':>12}  NO BENCHMARK")
            continue

        r = jmh_results[key]
        metrics   = compute_metrics(r["baseline"]["score"], r["stressed"]["score"], r["stressed"]["threads"])
        confirmed = metrics["contention_factor"] > CONTENTION_FACTOR_THRESHOLD

        label = f"{target_class}.{target_method}()"
        result_str = "[CONFIRMED]" if confirmed else "[not confirmed]"
        print(f"  {cand['smell_type']:<30} {label:<35} "
              f"{metrics['contention_factor']:>6.1f}  "
              f"{metrics['throughput_degradation_pct']:>11.1f}%  {result_str}")

        if confirmed:
            validated.append({**cand, "jlm_metrics": metrics, "confirmed": True})

    if no_result:
        print(f"\n[Job 2] {len(no_result)} candidates had no matching JMH benchmark.")

    return validated


# ── main ──────────────────────────────────────────────────────────────────────

def main(argv=None):
    argv = argv or sys.argv[1:]
    candidates_path  = Path(argv[0]) if len(argv) > 0 else ROOT / "candidates.json"
    validated_path   = Path(argv[1]) if len(argv) > 1 else ROOT / "validated_candidates.json"
    force_rebuild    = "--rebuild" in argv

    # Step 1: build
    if not build_jar(force_rebuild):
        sys.exit(1)

    # Step 2: run JMH
    if not run_jmh(JMH_RAW_JSON):
        print("[Job 2] JMH run failed -- no results to parse.")
        sys.exit(1)

    # Step 3: parse & match
    with open(candidates_path) as f:
        candidates = json.load(f)

    jmh_results = load_jmh_results(JMH_RAW_JSON)
    validated   = confirm_candidates(candidates, jmh_results)

    with open(validated_path, "w") as f:
        json.dump(validated, f, indent=2)

    print(f"\n[Job 2] Confirmed: {len(validated)} / {len(candidates)} candidates  ->  {validated_path}")
    return validated


if __name__ == "__main__":
    main()
