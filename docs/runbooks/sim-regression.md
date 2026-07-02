# Runbook: SUMO sim-regression CI

**Audience:** DevOps engineer (runner provisioning), traffic engineer (baseline updates).
**Workflow:** [`.github/workflows/sim-regression.yml`](../../.github/workflows/sim-regression.yml).
**Comparison tool:** [`simulation/compare_kpis.py`](../../simulation/compare_kpis.py).
**Tests:** [`simulation/tests/test_compare_kpis.py`](../../simulation/tests/test_compare_kpis.py) — 19 tests covering grading + format + CLI exit codes.

---

## 1. What the workflow does

For every PR touching `simulation/`, `services/decision-engine/`, `services/traffic-controller/`, or `shared/atms_common/`, the workflow:

1. Runs each scenario under `simulation/scenarios/` end-to-end with `python -m simulation <name>`.
2. Diffs the resulting `simulation/out/<name>/kpis.json` against the committed `simulation/baselines/<name>.json`.
3. Posts a markdown table of the diff to the PR (sticky comment per scenario).
4. Fails the workflow if any scenario regresses on:
   - `avg_delay_s` > baseline × 1.10
   - `max_queue_length` > baseline × 1.10
   - `throughput_vph` < baseline × 0.95
   - `conflicts` > 0 (any conflict is a hard fail)
5. Logs `preempt_events` and `ped_calls_served` drift as informational rather than fatal.

Tolerances live per-scenario in `simulation/baselines/<scenario>.json` under a `tolerances` block; defaults match the list above.

---

## 2. Provisioning the self-hosted runner

The workflow uses `runs-on: [self-hosted, sumo-runner]`. GitHub-hosted runners do not ship SUMO; we need a small self-hosted pool with the binary installed.

### 2.1 Hardware

- Linux x86_64 VM or bare metal.
- 4 vCPU / 8 GB RAM is sufficient for the rush-hour scenario; larger scenarios may need more.
- 20 GB disk for SUMO + Python venvs + run artefacts (retained 14 days).

### 2.2 OS prep

```bash
sudo apt-get update
sudo apt-get install -y software-properties-common
sudo add-apt-repository -y ppa:sumo/stable
sudo apt-get update
sudo apt-get install -y sumo sumo-tools sumo-doc python3.11 python3.11-venv python3-pip git

sumo --version  # confirm
```

Set `SUMO_HOME` in the runner's environment:

```bash
echo 'export SUMO_HOME=/usr/share/sumo' >> ~/.bashrc
echo 'export PATH=$PATH:$SUMO_HOME/bin' >> ~/.bashrc
```

### 2.3 Install the GitHub runner

Follow GitHub's runner registration flow:

1. Org / repo → Settings → Actions → Runners → New self-hosted runner.
2. Apply the labels `self-hosted`, `Linux`, `X64`, and **`sumo-runner`** (the workflow matches on the last one).
3. Install as a systemd service:

```bash
sudo ./svc.sh install
sudo ./svc.sh start
```

### 2.4 Smoke test

From the runner, manually run a scenario:

```bash
git clone https://github.com/<org>/atms.git
cd atms
python3.11 -m venv .venv && . .venv/bin/activate
pip install -r services/decision-engine/requirements.txt
PYTHONPATH=$PWD python -m simulation rush-hour --max-steps 100
ls simulation/out/rush-hour/kpis.json   # expect file present
```

If the smoke test passes, trigger a workflow_dispatch from the GitHub UI to confirm end-to-end.

---

## 3. Capturing / updating a baseline

Baselines are **per-scenario** JSON files. The current baseline at `simulation/baselines/rush-hour.json` is a **placeholder** until the first canonical SUMO run captures real numbers.

### 3.1 Initial capture (when a scenario lands or the placeholder is replaced)

1. From a clean checkout of `main`, on the self-hosted runner:
   ```bash
   PYTHONPATH=$PWD python -m simulation <scenario> --max-steps 3600 --seed 42
   ```
2. Inspect `simulation/out/<scenario>/kpis.json`. Confirm `conflicts == 0` and the throughput / delay numbers look sane for the scenario.
3. Copy into the baselines dir:
   ```bash
   jq '{
     scenario: .scenario,
     captured_at: (now | strftime("%Y-%m-%d")),
     captured_git_sha: env.GIT_SHA,
     captured_sumo_version: env.SUMO_VERSION,
     captured_seed: 42,
     captured_max_steps: 3600,
     kpis: .,
     tolerances: {
       delay_pct_tolerance: 0.10,
       queue_pct_tolerance: 0.10,
       throughput_pct_tolerance: 0.05,
       preempt_abs_tolerance: 1,
       ped_abs_tolerance: 1
     }
   }' simulation/out/<scenario>/kpis.json > simulation/baselines/<scenario>.json
   ```
4. Commit the baseline to `main`. Subsequent PRs are gated against it.

### 3.2 Updating an existing baseline (intentional KPI change)

When a model / policy change legitimately moves the KPIs (e.g., a new decision-engine version that increases throughput at the cost of slightly more delay), update the baseline **explicitly** in the same PR that changes the code.

Workflow:

1. Run the new code locally / on the runner to produce the new KPIs.
2. Replace the relevant fields in `simulation/baselines/<scenario>.json`.
3. Update `captured_git_sha` to the new HEAD.
4. Get the change reviewed by a second engineer — the baseline is the floor for all future PRs, so changes need a sign-off.
5. Land the PR. The sim-regression workflow will now compare future PRs against the new baseline.

Do **not** update the baseline silently in a code-change PR; that defeats the regression check. If the workflow flags a regression you believe is intentional, treat that as the moment to update the baseline.

### 3.3 Tolerance changes

Tolerances are per-scenario, not global. To loosen / tighten:

```json
"tolerances": {
  "delay_pct_tolerance": 0.05,
  "throughput_pct_tolerance": 0.03
}
```

Same review rule applies: a separate PR or visible block in the same PR description.

---

## 4. Local development

Engineers can run the same check locally before pushing:

```bash
PYTHONPATH=$PWD python -m simulation rush-hour
PYTHONPATH=$PWD python -m simulation.compare_kpis \
    --scenario rush-hour \
    --kpis simulation/out/rush-hour/kpis.json
echo "exit: $?"  # 0=pass, 1=regression, 2=missing input
```

The local SUMO install can be `eclipse-sumo` from pip (no apt needed, slightly older releases). The output may differ slightly from the runner's SUMO version, so the local check is advisory — the CI run is authoritative.

---

## 5. Adding a new scenario

1. Create `simulation/scenarios/<name>/` with `network.net.xml`, `routes.rou.xml`, `detectors.add.xml`, `config.sumocfg`.
2. Add the scenario name to the workflow's matrix:
   ```yaml
   matrix:
     scenario: [rush-hour, <new-name>]
   ```
3. Capture an initial baseline (§3.1).
4. Land both changes in the same PR.

---

## 6. Failure modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| Workflow stuck on "Waiting for a runner" | No self-hosted runner with `sumo-runner` label is online | Restart the runner systemd unit; confirm label in GitHub UI |
| `sumo --version` step fails | SUMO not installed on runner | Repeat §2.2 on the runner |
| `traci.exceptions.TraCIException: ...` | Scenario XML invalid or detector mismatch | Reproduce locally with `python -m simulation <name>` and inspect SUMO's stderr |
| `compare_kpis` exits 2 (missing baseline) | First run of a new scenario, or accidentally deleted | Capture a baseline per §3.1 |
| PR comment never appears | `pull-requests: write` permission missing or fork PR (forks can't post comments) | Run via `workflow_dispatch` and check the artefact `sim-diff-<scenario>.md` |
| `pip install eclipse-sumo` fails | Wheel not built for the runner's CPU/glibc combination | Use the apt path (§2.2) instead |

---

## 7. Out of scope

- **Multi-intersection scenarios.** Only single-intersection scenarios are wired today. The harness's `runner.py` accepts only one TraCI session at a time; multi-junction sim is a Phase 4 (pilot-rollout) item.
- **Real-traffic replay.** The scenarios are synthetic. Once production data is flowing, a "real-trace" scenario fed from anonymised production data is a D2 follow-up.
- **GPU benchmarks.** Sim-regression doesn't measure inference latency. That belongs in a separate D1-serving benchmark CI job once the model registry promotion path exists.
