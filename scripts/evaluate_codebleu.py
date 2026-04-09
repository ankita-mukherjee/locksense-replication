#!/usr/bin/env python3
"""
LockSense Replication Script — CodeBLEU Evaluation (Table 9)

Computes CodeBLEU scores for generated patches vs. reference fixes.
Reproduces the RQ3 numbers reported in the paper.

Usage:
    python scripts/evaluate_codebleu.py \
        --generated  data/patches/generated/  \
        --reference  data/patches/reference/  \
        --output     data/codebleu_results.json

Requires:
    pip install codebleu
"""

import argparse
import json
import os
from pathlib import Path

try:
    from codebleu import calc_codebleu
except ImportError:
    raise ImportError("Install codebleu: pip install codebleu")


def load_patches(directory: str) -> dict:
    """Load all .java patch files from a directory, keyed by filename stem."""
    patches = {}
    for path in sorted(Path(directory).glob("*.java")):
        patches[path.stem] = path.read_text(encoding="utf-8")
    return patches


def evaluate(generated_dir: str, reference_dir: str, output_path: str):
    generated = load_patches(generated_dir)
    reference  = load_patches(reference_dir)

    common_keys = sorted(set(generated) & set(reference))
    if not common_keys:
        raise ValueError("No matching patch files found between generated and reference directories.")

    results = []
    for key in common_keys:
        score = calc_codebleu(
            references=[reference[key]],
            predictions=[generated[key]],
            lang="java",
            weights=(0.25, 0.25, 0.25, 0.25),  # ngram, weighted, ast, dataflow
        )
        results.append({
            "candidate": key,
            "codebleu":        round(score["codebleu"], 4),
            "ngram_bleu":      round(score["ngram_match_score"], 4),
            "weighted_bleu":   round(score["weighted_ngram_match_score"], 4),
            "syntax_match":    round(score["syntax_match_score"], 4),
            "dataflow_match":  round(score["dataflow_match_score"], 4),
        })

    avg = {
        "candidate": "AVERAGE",
        "codebleu":        round(sum(r["codebleu"]       for r in results) / len(results), 4),
        "ngram_bleu":      round(sum(r["ngram_bleu"]     for r in results) / len(results), 4),
        "weighted_bleu":   round(sum(r["weighted_bleu"]  for r in results) / len(results), 4),
        "syntax_match":    round(sum(r["syntax_match"]   for r in results) / len(results), 4),
        "dataflow_match":  round(sum(r["dataflow_match"] for r in results) / len(results), 4),
    }
    results.append(avg)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"Evaluated {len(results)-1} patch pairs.")
    print(f"Average CodeBLEU: {avg['codebleu']}")
    print(f"Results written to: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute CodeBLEU for LockSense patches.")
    parser.add_argument("--generated", required=True, help="Directory of generated .java patches")
    parser.add_argument("--reference",  required=True, help="Directory of reference .java patches")
    parser.add_argument("--output",     default="data/codebleu_results.json")
    args = parser.parse_args()
    evaluate(args.generated, args.reference, args.output)
