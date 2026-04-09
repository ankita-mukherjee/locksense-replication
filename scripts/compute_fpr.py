#!/usr/bin/env python3
"""
LockSense Replication Script — FPR Computation (Tables 7, 8)

Reads candidates.json (Job 1 output) and validated_candidates.json
(Job 2 output) and computes per-project FPR, reproducing RQ2 results.

Usage:
    python scripts/compute_fpr.py \
        --candidates  data/candidates/bankapp_candidates.json \
        --validated   data/validated/bankapp_validated.json
"""

import argparse
import json


def compute_fpr(candidates_path: str, validated_path: str):
    with open(candidates_path, encoding="utf-8") as f:
        candidates = json.load(f)
    with open(validated_path, encoding="utf-8") as f:
        validated = json.load(f)

    flagged   = len(candidates)
    confirmed = len(validated)
    fp        = flagged - confirmed
    fpr       = fp / flagged if flagged > 0 else 0.0

    print(f"Flagged by Job 1 : {flagged}")
    print(f"Confirmed by Job 2: {confirmed}")
    print(f"False Positives  : {fp}")
    print(f"FPR              : {fpr:.1%}")
    return fpr


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute FPR for LockSense pipeline.")
    parser.add_argument("--candidates", required=True, help="Path to candidates.json")
    parser.add_argument("--validated",  required=True, help="Path to validated_candidates.json")
    args = parser.parse_args()
    compute_fpr(args.candidates, args.validated)
