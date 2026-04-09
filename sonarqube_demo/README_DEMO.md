# SonarQube Demo – LockSense Justification

## Goal
Show that SonarQube detects only the **simple** lock contention case (SimpleBank)
but **misses** three complex smells (SessionManager, OrderProcessor, ReportBuilder).
This justifies the need for LockSense in the paper.

---

## Step 1 – Generate a SonarQube token

1. Open http://localhost:9000 in your browser
2. Log in (default: admin / admin, or admin / the password you set)
3. Go to: **My Account → Security → Generate Tokens**
4. Name it `locksense-demo`, click **Generate**
5. **Copy the token** (shown only once, starts with `sqp_...`)

---

## Step 2 – Run sonar-scanner

Open a **Command Prompt** and run (replace `<YOUR_TOKEN>` with the token from Step 1):

```
cd C:\Users\100996478\Locksense\sonarqube_demo

C:\Users\100996478\Documents\sonar-scanner-8.0.1.6346-windows-x64\bin\sonar-scanner.bat ^
  -Dsonar.token=<YOUR_TOKEN>
```

Wait for "EXECUTION SUCCESS" in the output (takes ~30-60 seconds).

---

## Step 3 – View results in SonarQube dashboard

1. Open http://localhost:9000/dashboard?id=locksense-demo
2. Click **Issues** tab → filter by **Rule**

### What you will see:

| Class | SonarQube Rule Fired | Smell LockSense Detects |
|---|---|---|
| `SimpleBank` | S2446 / synchronized method | `synchronized_method` ✓ Both detect |
| `SessionManager` | **NONE** | `unified_locking` ← LockSense only |
| `OrderProcessor` | **NONE** | `loop_inside_critical`, `loop_outside_critical` ← LockSense only |
| `ReportBuilder` | **NONE** | `overly_split` ← LockSense only |

SonarQube fires on ~1 of 4 classes (25% detection rate for these smells).
LockSense detects all 4 classes with 0 false negatives on these patterns.

---

## Step 4 – Run LockSense Job 1 on the same files

```
cd C:\Users\100996478\Locksense

python job1_detect.py sonarqube_demo\src\main\java\com\locksense\demo candidates_demo.json
```

Compare the `candidates_demo.json` output against SonarQube's Issues tab to
show in the paper / presentation that LockSense catches what SonarQube misses.
