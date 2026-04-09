# LockSense — Replication Package

> **Paper:** LockSense: Automated Lock Contention Detection and AI-Assisted Remediation in Java CI/CD Pipelines  
> **Venue:** ASE 2026, Sacramento, CA, USA  
> **Author:** Ankita Mukherjee, Ontario Tech University

---

## What is in this package

| Path | Contents |
|---|---|
| `job1_detect.py` | Job 1 — AST-based smell detection (6 smell types via javalang) |
| `job2_jmh_runner.py` | Job 2 — JMH runtime validation (CF + Mann-Whitney U) |
| `job3_remediate.py` | Job 3 — Local LLM remediation via Ollama |
| `run_pipeline.py` | End-to-end pipeline runner |
| `.locksense.yml` | Reproducibility spec (model SHA-256, temperature, seed) |
| `jmh_harness/` | JMH Maven project — benchmark harness for Job 2 |
| `data/candidates/` | Job 1 output for all five subject projects |
| `data/raw_jmh/` | Raw JMH JSON measurement data from Job 2 |
| `scripts/evaluate_codebleu.py` | CodeBLEU evaluation script (Table 9) |
| `scripts/compute_fpr.py` | FPR computation script (Tables 7, 8) |
| `.github/workflows/locksense.yml` | GitHub Actions CI/CD workflow |

---

## Requirements

```
Python 3.11+
Java 17 (OpenJDK)
Maven 3.9+
Ollama (https://ollama.com) — local LLM server
Docker (optional, for full CI/CD run)
```

Python packages:
```bash
pip install javalang scipy codebleu
```

---

## Reproducing the results

### Step 1 — Start Ollama and pull the model

```bash
ollama serve &
ollama pull qwen2.5-coder:7b
```

### Step 2 — Run the full pipeline on a Java project

```bash
python run_pipeline.py <path-to-java-project> candidates.json validated_candidates.json
```

### Step 3 — Reproduce Table 8 (FPR)

```bash
python scripts/compute_fpr.py \
  --candidates data/candidates/bankapp_candidates.json \
  --validated  data/validated/bankapp_validated.json
```

### Step 4 — Reproduce Table 9 (CodeBLEU)

```bash
python scripts/evaluate_codebleu.py \
  --generated data/patches/generated/ \
  --reference data/patches/reference/ \
  --output    data/codebleu_results.json
```

### Step 5 — Build and run the JMH harness manually

```bash
cd jmh_harness
mvn package -q
java -jar target/locksense-benchmarks.jar -rf json -rff jmh_result.json
```

---

## Key configuration (from `.locksense.yml`)

| Parameter | Value |
|---|---|
| Model | qwen2.5-coder:7b |
| Temperature | 0.2 |
| Seed | 42 |
| JMH warmup iterations | 5 |
| JMH measurement iterations | 10 |
| CF threshold | > 1.05 |
| Statistical test | Mann-Whitney U, α = 0.05 |
| Threads (baseline / stress) | 1 / 8 |

---

## Subject projects

| Project | LOC | Domain |
|---|---|---|
| Apache HBase | 1.2M | Distributed DB |
| Glide | 180K | Image library |
| EventBus | 15K | Event dispatch |
| Apache Cassandra | 700K | Distributed DB |
| Apache Tomcat | 500K | Web server |

---

## Citation

```bibtex
@inproceedings{mukherjee2026locksense,
  author    = {Ankita Mukherjee},
  title     = {{LockSense}: Automated Lock Contention Detection and
               {AI}-Assisted Remediation in {Java} {CI/CD} Pipelines},
  booktitle = {Proceedings of the 41st IEEE/ACM International Conference
               on Automated Software Engineering (ASE)},
  year      = {2026},
  address   = {Sacramento, CA, USA},
  publisher = {ACM}
}
```
