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