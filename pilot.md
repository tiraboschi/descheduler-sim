# Pilot Scenario

Simulates a real-world KubeVirt cluster running a mixed pipeline workload with
business-hours load patterns, intra-day spikes, and overnight batch jobs.

## Cluster topology

| Property | Value |
|----------|-------|
| Nodes | 10 (3 masters + 7 workers), all schedulable for VMs |
| CPU per node | 128 cores |
| Memory per node | 2.3 TiB (2355 GiB) |
| Network | 10 Gbps shared |
| Migration limits | 5 concurrent cluster-wide, 2 outbound per node |

## VM fleet — 148 VMs

| Class | Count | CPU | Memory | Dirty rate |
|-------|------:|-----|--------|------------|
| `8c80g` | 56 | 8c | 80Gi | 500 – 4000 Mbps (memory-intensive pipeline steps) |
| `8c64g` | 61 | 8c | 64Gi | 200 – 2000 Mbps (mixed) |
| `8c32g` | 3 | 8c | 32Gi | 400 Mbps |
| `4c16g` | 24 | 4c | 16Gi | 200 Mbps |
| `4c8g` | 4 | 4c | 8Gi | 50 Mbps |

Base utilization: **CPU 10%** (off-peak idle), **Memory 54%** (stable — fixed allocations).

## Workload pattern

| Generator | Interval | Target | Effect |
|-----------|----------|--------|--------|
| `background-hum` | 3 m | 3 random nodes | Sustains the off-peak floor (~20% cluster CPU) |
| `business-hours-hotspot` | 5 m | hottest-CPU node | Heat-and-chase driving CPU toward 30% average |
| `business-hours-spread` | 7 m | top-2 CPU nodes | Broadens imbalance across two nodes simultaneously |
| `spike-injector` | 15 m | random node | ~4 spikes per 60-min run — models "1-3 spikes/day, 10-20% above baseline, 1-3 h duration"; bursts to ~47% peak |
| `memory-pipeline-load` | 10 m | hottest-memory node | Memory-intensive batch tasks; exercises the memory dimension of the scoring formula and produces longer migrations |

Duration: **60 minutes real-time** (`timeScale: 1.0`) so all Prometheus windows,
recording rules, and the 5-minute descheduler cycle run on wall-clock time.

## Files

| File | Contents |
|------|----------|
| `k8s/pilot-nodes.yaml` | 10 KWOK nodes (`pilot-master-0{1-3}`, `pilot-worker-0{1-7}`) |
| `k8s/pilot-vms.yaml` | 148 VirtualMachine objects |
| `k8s/pilot-scenario.yaml` | SimulationScenario `pilot-biz-hours` |

## How to run

```bash
# Bootstrap the simulation environment using the pilot topology directly —
# no default kwok-node-* nodes or example VMs are created.
./setup-kind-env.sh --pilot

# Wait for all 148 virt-launcher pods to be Running
kubectl wait --for=condition=Ready pod -l app=virt-launcher --timeout=300s

# Start the scenario
kubectl apply -f k8s/pilot-scenario.yaml
```

## What to observe

- **CPU utilization per node** rises unevenly as business-hours and spike generators fire.
- **Descheduler** (5-minute cycle) evicts VMs from overutilized nodes, limited to 2 per node per cycle and 5 cluster-wide.
- **KubevirtMigrationAware cooldown** blocks re-eviction of recently migrated VMs; watch the cooldown multiplier drop on nodes that have been evicted from repeatedly.
- **Memory-heavy migrations** (8c/80Gi VMs at up to 4000 Mbps dirty rate) take longer and raise the probability of in-flight migration blocks.
- After 3-4 descheduler cycles (~15-20 minutes) utilization should visibly rebalance.

---

# Week Scenario

Extends the pilot topology with a full 7-day workload cycle.  Uses the same
cluster and VM fleet but adds day-of-week patterns, overnight batch jobs, and a
weekend load profile to validate descheduler **stability** and correct
**on/off-peak transitions** over an extended period.

All timing runs at `timeScale: 1.0` — no compression — so Prometheus windows,
descheduler cooldown periods, and VM migration durations stay consistent with a
real cluster.

## Files

| File | Contents |
|------|----------|
| `k8s/pilot-nodes.yaml` | Shared — same 10-node topology as the pilot |
| `k8s/pilot-vms.yaml` | Shared — same 148 VMs |
| `k8s/week-scenario.yaml` | SimulationScenario `week-pilot` |

## Simulated start time

```yaml
simulatedStartTime: "2026-06-15T00:00:00"  # Monday 00:00
```

The simulated clock is anchored to this ISO timestamp so the week always starts
from Monday regardless of the real day when the CR is applied.  Update this to
the upcoming Monday before each run.

## Customer workload targets

| Metric | Off-peak | Business hours (avg) | Worst-case spike |
|--------|----------|---------------------|-----------------|
| CPU cluster-wide | ~20% | ~30% | ~47% |
| Memory cluster-wide | ~54% (stable) | ~55% | ~68% (overnight batch) |

## Weekly generator schedule

| Generator | Active window | Node selector | Task type | Rate | Interval |
|-----------|--------------|---------------|-----------|-----:|---------|
| `fleet-offpeak-background` | always (24 × 7) | all nodes, 30 VMs each | `offpeak-background` | 8 | 5 m |
| `weekday-biz-hotspot` | Mon–Fri 10:00–18:00 | hottest-CPU node, 3–6 VMs | `business-hours` | 5 | 5 m |
| `weekday-biz-spread` | Mon–Fri 10:00–18:00 | top-2 CPU nodes, 2–4 VMs | `business-hours` | 2 | 7 m |
| `tuesday-boost` | Tue 10:00–18:00 | hottest-CPU node, 3–6 VMs | `business-hours` | 3 | 5 m |
| `weekday-spike-injector` | Mon–Fri 10:00–18:00 | 2 random nodes, 2–5 VMs | `business-spike` | 10 | 15 m |
| `overnight-batch` | 22:00–06:00 (every night) | 3 random nodes, 2–4 VMs | `memory-batch` | 13 | 5 m |
| `weekend-load` | Sat–Sun 10:00–18:00 | hottest-CPU node, 3–5 VMs | `weekend-workload` | 4 | 5 m |

### Load layer model

```
VM baseline (pilot-vms.yaml):           CPU 10%,  memory 49%
+ fleet-offpeak-background (24 × 7):   +11% CPU, +5.5% memory on all VMs
  → off-peak cluster:                   ~20% CPU, ~54% memory

+ weekday-biz-hotspot + biz-spread:    concentrated on 1–2 nodes
  → business-hours cluster avg:         ~30% CPU (hot nodes ~57%)

+ tuesday-boost (Tuesdays only):        rate 5 → 8 on hottest node
  → Tuesday peak:                       slightly above standard weekday

+ weekday-spike-injector (every 15 m): 2 random nodes burst
  → cluster peak during spike:          ~47% CPU

+ overnight-batch (22:00–06:00):        memory-intensive tasks on 3 nodes
  → cluster memory max:                 ~68%

weekend-load replaces biz-* generators: rate 4 vs 5, no spread, no tuesday-boost
  → weekend cluster avg:                ~10% below weekday business hours
```

### Task types

`offpeak-background`, `business-hours`, `business-spike`, and `memory-batch`
are identical to the pilot scenario.  One new type is added:

| Type | CPU | Memory | Duration |
|------|-----|--------|---------|
| `weekend-workload` | 0.12–0.22, mean 0.17 (normal) | 0.02–0.06 (uniform) | 1800–5400 s, mean 3600 s (exponential) |

Same shape as `business-hours` but a lower CPU mean to produce the ~10% weekend reduction.

## `activeWindows` — day-of-week and overnight support

Generators that should only fire during specific windows carry an
`activeWindows` list.  Each window supports two optional fields:

```yaml
activeWindows:
  - days: [Mon, Tue, Wed, Thu, Fri]  # optional — list of short day names
    start: "10:00"
    end:   "18:00"

  # Overnight window: end < start wraps across midnight
  - start: "22:00"
    end:   "06:00"
```

**Overnight + days semantics:** for a window where `start > end`, the
after-midnight portion (00:00 – `end`) is attributed to the **previous** day.
This means `days: [Mon], start: "22:00", end: "06:00"` correctly covers both
Monday 22:00–23:59 and Tuesday 00:00–06:00 without listing Tuesday in `days`.

## How to run

```bash
# Reuse the pilot environment (nodes and VMs are already applied).
# Update simulatedStartTime to the upcoming Monday, then:
kubectl apply -f k8s/week-scenario.yaml

# Monitor the scenario status
kubectl get simulationscenario week-pilot -o yaml

# Stop early by deleting the CR (active tasks drain naturally)
kubectl delete simulationscenario week-pilot
```

## What to observe

- **Off-peak periods** (before 10:00 and after 18:00 on weekdays): all
  business-hours generators are inactive; CPU settles back to ~20% cluster-wide;
  descheduler should be mostly quiet.
- **Business-hours transitions** (10:00 daily): hotspot and spread generators
  activate; one or two nodes climb toward 57%; descheduler begins migrating
  within the first 5-minute cycle.
- **Tuesday**: cluster CPU slightly higher than other weekdays due to the extra
  `tuesday-boost` generator (effective rate 8 vs 5 on the hottest node).
- **Intra-day spikes** (every 15 minutes during business hours): two random
  nodes burst; cluster avg briefly reaches ~47%; descheduler responds within one
  cycle and the spike drains within 1–3 hours.
- **Overnight batch** (22:00–06:00): memory utilization rises on three random
  nodes toward the ~68% cluster-wide max; longer migration times for
  memory-intensive VMs are expected.
- **Weekend** (Sat–Sun 10:00–18:00): `weekend-load` fires at rate 4 instead of
  5, no spread generator, no tuesday-boost; cluster CPU visibly lower than
  weekday business hours (~10% reduction).
- **Stability over 7 days**: no metric drift, no goroutine leaks in the
  scenario controller, eviction counts proportional across days.