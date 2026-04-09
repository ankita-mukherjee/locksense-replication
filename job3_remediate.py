#!/usr/bin/env python3
"""
LockSense Job 3: AI-Assisted Remediation
Reads validated_candidates.json, calls Claude API with a 5-component structured
prompt (source, smell classification, JLM metrics, refactoring template, Java
version), validates that the generated diff compiles, and writes
remediation_results.json.

Requires: ANTHROPIC_API_KEY environment variable
"""

import json
import os
import sys
import subprocess
import tempfile
import shutil
import requests
from pathlib import Path


# ─────────────── refactoring templates (per smell type) ─────────────────────

REFACTORING_TEMPLATES = {
    "synchronized_method": (
        "Remove the `synchronized` modifier from the method signature. "
        "Identify the minimal critical section (only the statements that read or write shared state) "
        "and wrap ONLY those statements in a `synchronized(this)` block. "
        "Move validation, I/O, and computation that does not touch shared fields OUTSIDE the lock."
    ),
    "loop_outside_critical": (
        "Move the `synchronized` block OUTSIDE the loop so the lock is acquired ONCE per method "
        "invocation rather than once per iteration. Accumulate results in a local variable inside "
        "the loop and flush to shared state in a single synchronized block after the loop ends."
    ),
    "overly_split": (
        "Merge the two (or more) consecutive `synchronized(lock)` blocks on the same lock object "
        "within this method into a single `synchronized(lock)` block. "
        "The combined block must preserve all shared-state updates in their original order."
    ),
    "unified_locking": (
        "Split the single lock into one lock per independent data structure "
        "(e.g., `sessionsLock`, `auditLock`, `counterLock`). "
        "Replace each `synchronized(sessionLock)` block with the appropriate fine-grained lock. "
        "For simple numeric counters consider replacing the lock with `java.util.concurrent.atomic.AtomicInteger`."
    ),
    "loop_inside_critical": (
        "Move the loop OUTSIDE the `synchronized` block. Pre-compute any read-only data before "
        "acquiring the lock, then acquire the lock once to apply the final write, then release it."
    ),
    "same_lock": (
        "Introduce separate lock objects for each logically independent group of shared fields. "
        "Replace the single shared lock with per-group locks so that unrelated methods no longer "
        "serialize against each other."
    ),
}


# ─────────────── read source snippet ────────────────────────────────────────

def read_snippet(candidate, java_base_dir="."):
    """
    Return the source lines for the candidate's method (± 5 lines of context).
    Searches for the Java file starting from java_base_dir.
    """
    file_path = candidate.get("file_path", "")
    fname = Path(file_path).name

    # Try to find the file relative to the base dir, or by name anywhere
    search_paths = [
        Path(java_base_dir) / file_path,
        Path(java_base_dir) / fname,
    ]
    src_file = None
    for p in search_paths:
        if p.exists():
            src_file = p
            break

    if src_file is None:
        return f"// Source file not found: {file_path}"

    lines = src_file.read_text(encoding="utf-8").splitlines()
    start = max(0, candidate.get("start_line", 1) - 1 - 5)
    end   = min(len(lines), candidate.get("end_line", 1) + 5)
    return "\n".join(f"{i+1:4d}  {l}" for i, l in enumerate(lines[start:end]))


# ─────────────── prompt assembly ────────────────────────────────────────────

def build_prompt(candidate, snippet):
    smell   = candidate["smell_type"]
    metrics = candidate.get("jlm_metrics", {})
    templ   = REFACTORING_TEMPLATES.get(smell, "Refactor to reduce lock contention.")

    prompt = f"""You are a Java concurrency expert.
Generate a minimal unified diff that refactors the lock contention smell described below.
Output ONLY the unified diff in standard format (--- a/path, +++ b/path), no explanation.

[1] SOURCE CODE (synchronized region + context):
```java
{snippet}
```

[2] SMELL CLASSIFICATION:
Type: {smell}  |  Severity: {candidate.get('severity_score', 'N/A')}
Class: {candidate.get('class')}  |  Method: {candidate.get('method')}()

[3] RUNTIME METRICS (multi-threaded vs single-threaded):
ΔHTM  (hold-time increase):    {metrics.get('delta_htm_pct',  'N/A')}%
ΔGETS (acquisition increase):  {metrics.get('delta_gets_pct', 'N/A')}%
Blocked count (proxy SPIN):    {metrics.get('spin_count',     'N/A')}
Thread count used:             {metrics.get('thread_count_used', 'N/A')}
Contention factor:             {metrics.get('contention_factor', 'N/A')}x

[4] REFACTORING TEMPLATE:
{templ}

[5] JAVA VERSION: 17

Output a unified diff (--- a/{Path(candidate['file_path']).name} +++ b/{Path(candidate['file_path']).name}).
"""
    return prompt


# ─────────────── Claude API call ────────────────────────────────────────────

def call_claude(prompt, api_key):
    headers = {
        "x-api-key":         api_key,
        "anthropic-version": "2023-06-01",
        "content-type":      "application/json",
    }
    body = {
        "model":      "claude-sonnet-4-6",
        "max_tokens": 2048,
        "temperature": 0.2,
        "messages": [{"role": "user", "content": prompt}],
    }
    resp = requests.post("https://api.anthropic.com/v1/messages",
                         headers=headers, json=body, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return data["content"][0]["text"]


# ─────────────── diff extraction ────────────────────────────────────────────

def extract_diff(text):
    """Pull the unified diff block out of the LLM response."""
    lines = text.splitlines()
    in_diff = False
    diff_lines = []
    for line in lines:
        if line.startswith("--- ") or line.startswith("diff "):
            in_diff = True
        if in_diff:
            diff_lines.append(line)
    return "\n".join(diff_lines) if diff_lines else text


# ─────────────── compile check (Gate 1) ─────────────────────────────────────

def try_apply_and_compile(candidate, diff_text, java_base_dir, compile_dir):
    """
    Apply the diff to a temp copy of the source and run javac.
    Returns (status, message)  where status in {"compilable","compile_failed","apply_failed"}
    """
    fname = Path(candidate["file_path"]).name

    # Find original source
    orig = None
    for p in [Path(java_base_dir) / candidate["file_path"],
              Path(java_base_dir) / fname]:
        if p.exists():
            orig = p
            break
    if orig is None:
        return "apply_failed", f"Source not found: {fname}"

    # Write diff to temp file
    with tempfile.NamedTemporaryFile("w", suffix=".patch",
                                     delete=False, encoding="utf-8") as pf:
        pf.write(diff_text)
        patch_path = pf.name

    # Work in a temp directory
    work_dir = Path(tempfile.mkdtemp())
    shutil.copy(orig, work_dir / fname)

    try:
        # git apply --check
        check = subprocess.run(
            ["git", "apply", "--check", patch_path],
            cwd=str(work_dir), capture_output=True, text=True
        )
        if check.returncode != 0:
            # Try 3-way merge
            check = subprocess.run(
                ["git", "apply", "--3way", patch_path],
                cwd=str(work_dir), capture_output=True, text=True
            )
            if check.returncode != 0:
                return "apply_failed", check.stderr.strip()

        # Apply
        subprocess.run(["git", "apply", patch_path],
                        cwd=str(work_dir), check=True, capture_output=True)

        # Compile – only need to compile the one patched file
        result = subprocess.run(
            ["javac", str(work_dir / fname)],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            return "compilable", "OK"
        else:
            return "compile_failed", result.stderr.strip()
    except Exception as e:
        return "compile_failed", str(e)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
        os.unlink(patch_path)


# ─────────────── main ────────────────────────────────────────────────────────

def main(argv=None):
    argv = argv or sys.argv[1:]
    in_file      = argv[0] if len(argv) > 0 else "validated_candidates.json"
    out_file     = argv[1] if len(argv) > 1 else "remediation_results.json"
    java_base    = argv[2] if len(argv) > 2 else "lock_examples"
    compile_dir  = argv[3] if len(argv) > 3 else "lock_examples"

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("[Job 3] WARNING: ANTHROPIC_API_KEY not set – skipping LLM calls.")
        print("        Set the env var and re-run, or review candidates manually.")

    with open(in_file) as f:
        candidates = json.load(f)

    if not candidates:
        print("[Job 3] No confirmed candidates to remediate.")
        with open(out_file, "w") as f:
            json.dump([], f, indent=2)
        return

    results = []
    for cand in candidates:
        smell  = cand["smell_type"]
        cls    = cand["class"]
        method = cand["method"]
        print(f"\n[Job 3] Remediating: {smell}  {cls}.{method}()")

        snippet = read_snippet(cand, java_base)
        prompt  = build_prompt(cand, snippet)

        diff_text        = None
        remediation_status = "skipped"
        compile_msg      = "N/A"
        raw_response     = ""

        if api_key:
            try:
                raw_response = call_claude(prompt, api_key)
                diff_text    = extract_diff(raw_response)

                # Gate 1: compile check
                remediation_status, compile_msg = try_apply_and_compile(
                    cand, diff_text, java_base, compile_dir
                )
                print(f"         Gate 1 compile: {remediation_status}  – {compile_msg}")
            except Exception as e:
                remediation_status = "error"
                compile_msg = str(e)
                print(f"         ERROR calling API: {e}")
        else:
            # No API key – emit a template-based placeholder diff
            diff_text = (
                f"--- a/{Path(cand['file_path']).name}\n"
                f"+++ b/{Path(cand['file_path']).name}\n"
                f"@@ TODO @@\n"
                f" // Refactoring template for {smell}:\n"
                f" // {REFACTORING_TEMPLATES.get(smell, '')}\n"
            )
            remediation_status = "template_only"

        entry = {
            **cand,
            "diff":               diff_text,
            "remediation_status": remediation_status,
            "compile_message":    compile_msg,
            "raw_llm_response":   raw_response,
        }
        results.append(entry)

        # Print the diff for immediate feedback
        if diff_text:
            print("         ─── generated diff ───────────────────────────────")
            for line in (diff_text or "").splitlines()[:40]:
                print("        ", line)
            print("         ──────────────────────────────────────────────────")

    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)

    compiled = sum(1 for r in results if r["remediation_status"] == "compilable")
    print(f"\n[Job 3] {len(results)} remediations generated "
          f"({compiled} compilable)  ->  {out_file}")


if __name__ == "__main__":
    main()
