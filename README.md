# Kubernetes Descheduler with Prometheus Integration

Closed-loop testing environment for the Kubernetes Descheduler with real-time Prometheus metric feedback for load-aware VM rebalancing.

## Overview

This project provides a complete testing environment for the Kubernetes Descheduler integrated with:
- **Prometheus** for metrics collection and algorithm scoring via PromQL recording rules
- **KWOK** for simulating Kubernetes nodes without actual compute resources
- **VirtualMachine CRD** for representing KubeVirt-like VMs
- **SimulationScenario CRD** for creating dynamic, time-based workload patterns
- **Eviction Webhook** for handling VM migration on pod eviction
- **Synthetic Metrics Exporter** for generating realistic node metrics

The descheduler uses Prometheus metrics to identify overutilized and underutilized nodes, then evicts pods (triggering VM migrations) to rebalance the cluster.

## Architecture

```
┌────────────────────────────────────────────────────────────────┐
│                    Kubernetes Cluster (KIND)                   │
│                                                                │
│  ┌──────────────┐      ┌──────────────┐      ┌──────────────┐  │
│  │ Descheduler  │      │  Prometheus  │      │ KWOK Nodes   │  │
│  │              │◄─────┤              │◄─────┤              │  │
│  │ - Queries    │      │ - Scrapes    │      │ - Fake nodes │  │
│  │   metrics    │      │   metrics    │      │ - Run pods   │  │
│  │ - Evicts     │      │ - Recording  │      │              │  │
│  │   pods       │      │   rules      │      │              │  │
│  └──────┬───────┘      └──────────────┘      └──────────────┘  │
│         │                                                      │
│         │ eviction                                             │
│         ▼                                                      │
│  ┌──────────────┐      ┌──────────────┐      ┌──────────────┐  │
│  │  Eviction    │      │     VM       │      │    Metrics   │  │
│  │  Webhook     │─────►│  Controller  │      │   Exporter   │  │
│  │              │      │              │      │              │  │
│  │ - Intercepts │      │ - Manages VM │      │ - Reads pods │  │
│  │   evictions  │      │   lifecycle  │      │ - Calculates │  │
│  │ - Triggers   │      │ - Creates/   │      │   metrics    │  │
│  │   migrations │      │   deletes    │      │ - Exposes    │  │
│  │              │      │   pods       │      │   /metrics   │  │
│  └──────────────┘      └──────────────┘      └──────────────┘  │
│                                │                       │       │
│                                └───────────────────────┘       │
│                                    Reads/Updates pods          │
└────────────────────────────────────────────────────────────────┘
```

## Features

- **Real Kubernetes Descheduler**: Uses the actual descheduler from OpenShift/Kubernetes
- **Prometheus-Based Algorithms**: 19 load classification algorithms implemented as PromQL recording rules
- **Closed-Loop Simulation**: Evictions trigger migrations, which update metrics, which affect next evictions
- **Dynamic Workload Scenarios**: Create complex load patterns with SimulationScenarios
- **Node-Aware Task Generation**: Target VMs on most/least loaded nodes to test rebalancing
- **Stochastic Traffic Modeling**: Realistic workloads with Poisson/Normal/Exponential distributions
- **KubeVirt-Style VM Migration**: Mimics KubeVirt's VM lifecycle with virt-launcher pods
- **Eviction Protection**: Webhook prevents direct pod deletion, enforcing proper migration workflow
- **KWOK Integration**: Simulates nodes without actual compute resources
- **Docker & Podman Support**: Works with both container runtimes

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set up environment (auto-detects Docker/Podman)
./setup-kind-env.sh

# 3. Access services
# Prometheus: http://localhost:9090
# Metrics Exporter: http://localhost:8001
# Descheduler metrics: http://localhost:8443/metrics (via nginx proxy)

# 4. Watch the descheduler in action
kubectl logs -n kube-descheduler deployment/descheduler -f

# 5. Monitor VM migrations
kubectl get vm -w

# 6. Run a simulation scenario (optional)
kubectl apply -f k8s/example-scenario-simple.yaml
kubectl get scenarios -w
```

## Simulation Scenarios

Create dynamic workload patterns to test the descheduler:

```bash
# Apply a simple scenario (periodic traffic with random VM selection)
kubectl apply -f k8s/example-scenario-simple.yaml

# Apply a node-aware scenario (targets most/least loaded nodes)
kubectl apply -f k8s/example-scenario-node-aware.yaml

# Watch scenario execution
kubectl get scenarios -w
kubectl logs -l app=scenario-controller -f

# Monitor VM utilization changes
kubectl get vm -w
```

**Key Features:**
- **Node-Aware Targeting**: Generate load on most/least loaded nodes to create imbalance
- **Stochastic Tasks**: Realistic traffic patterns with Poisson/Normal/Exponential distributions
- **Dynamic Resources**: Tasks with varying CPU/memory consumption and duration
- **Scheduled Events**: Apply load patterns according to a timeline

**Note**: The scenario controller generates load patterns rapidly, but Prometheus metrics, recording rules, and the descheduler all operate on real time. Use `timeScale: 1.0` for realistic metric aggregations.

See [SCENARIO_GUIDE.md](SCENARIO_GUIDE.md) for complete documentation.

## Components

### Kubernetes Resources

| Component | File | Description |
|-----------|------|-------------|
| Descheduler | `k8s/descheduler.yaml` | Main descheduler deployment with LowNodeUtilization plugin |
| Descheduler Policy | `k8s/descheduler-policy.yaml` | Configuration for descheduling strategy |
| Prometheus | `k8s/prometheus.yaml` | Prometheus deployment for metrics |
| Recording Rules | `k8s/prometheus-rules.yaml` | PromQL rules for 19 algorithms |
| KWOK Nodes | `k8s/kwok-nodes.yaml` | 5 fake Kubernetes nodes |
| Metrics Exporter | `k8s/metrics-exporter.yaml` | Synthetic metrics generator |
| Eviction Webhook | `k8s/eviction-webhook.yaml` | Intercepts pod evictions |
| VM Controller | `k8s/vm-controller.yaml` | Manages VM lifecycle |
| VirtualMachine CRD | `k8s/virtualmachine-crd.yaml` | Custom resource definition for VMs |
| SimulationScenario CRD | `k8s/simulation-scenario-crd.yaml` | CRD for dynamic workload scenarios |
| Scenario Controller | `k8s/scenario-controller.yaml` | Executes simulation scenarios |

### Python Components

| Script | Purpose |
|--------|---------|
| `prometheus_exporter.py` | Generates synthetic node metrics from pod annotations |
| `eviction_webhook.py` | Handles pod eviction requests from descheduler |
| `vm_controller.py` | Manages VirtualMachine CR lifecycle |
| `scenario_controller.py` | Executes SimulationScenario CRs with dynamic task generation |
| `vm_manager.py` | Creates/updates VM custom resources |
| `pod_manager.py` | Manages virt-launcher pod lifecycle and migrations |
| `node.py` | Data structures for nodes and VMs |

### Setup Scripts

| Script | Purpose |
|--------|---------|
| `setup-kind-env.sh` | Automated KIND cluster setup with all components |
| `test-closed-loop.sh` | Test suite for verifying the environment |

## How It Works

### 1. Metrics Collection

The **Metrics Exporter** reads virt-launcher pod annotations from KWOK nodes and calculates:
- CPU usage ratio (sum of VM CPU consumption)
- CPU pressure (PSI - calculated from utilization)
- Memory usage ratio (sum of VM memory consumption)
- Memory pressure (PSI - calculated from utilization)

These metrics are exposed at `/metrics` for Prometheus to scrape.

### 2. Algorithm Scoring

**Prometheus Recording Rules** compute node scores using 19 different algorithms:
- Weighted Average
- Euclidean Distance
- Ideal Point Positive Distance
- Linear Amplified variations (k=1.0, k=3.0, k=5.0)
- And 14 more...

Example PromQL rule:
```yaml
- record: descheduler:node:linear_amplified_ideal_point_positive_distance:k3:avg1m
  expr: |
    # Calculate cluster averages
    # Calculate positive deviations
    # Amplify by k=3.0
    # Return node scores
```

### 3. Descheduling

The **Descheduler** runs every 60 seconds:
1. Queries Prometheus for node scores
2. Identifies overutilized nodes (score > cluster_avg + 10%)
3. Identifies underutilized nodes (score < cluster_avg)
4. Evicts up to 5 pods total (max 2 per node) from overutilized nodes

### 4. Migration

When the descheduler evicts a pod:
1. **Eviction Webhook** intercepts the eviction request
2. Marks the VM for migration (sets `evacuationNodeName` in VM status)
3. **VM Controller** detects the evacuation request
4. Deletes the old virt-launcher pod
5. Creates a new virt-launcher pod (without node assignment)
6. **Kubernetes Scheduler** places the pod on an available node
7. VM status is updated with new node assignment

### 5. Metrics Update

After migration:
1. Pod annotations move to the new node
2. Metrics Exporter recalculates node metrics
3. Prometheus scrapes updated metrics
4. Recording rules compute new scores
5. Descheduler sees updated cluster state in next cycle

This creates a **closed loop** where descheduling decisions affect the metrics that drive future decisions.

## Configuration

### Descheduler Policy

Edit `k8s/descheduler-policy.yaml` to configure:
- **Algorithm**: Change the PromQL query to use a different algorithm
- **Thresholds**: Adjust `thresholds.MetricResource` and `targetThresholds.MetricResource`
- **Eviction Limits**: Modify `maxNoOfPodsToEvictPerNode` and `maxNoOfPodsToEvictTotal`
- **Interval**: Change `--descheduling-interval` in `k8s/descheduler.yaml`

Current configuration:
```yaml
metricsUtilization:
  prometheus:
    query: descheduler:node:linear_amplified_ideal_point_positive_distance:k3:avg1m
  source: Prometheus
thresholds:
  MetricResource: 10  # Nodes with score > avg + 10% are overutilized
targetThresholds:
  MetricResource: 10  # Nodes with score < avg are underutilized
useDeviationThresholds: true
```

### Available Algorithms

See [PROMETHEUS_ALGORITHMS.md](PROMETHEUS_ALGORITHMS.md) for the complete list of algorithms and their PromQL implementations.

## Monitoring

### Prometheus Queries

Access Prometheus at http://localhost:9090/graph:

```promql
# Node scores (current algorithm)
descheduler:node:linear_amplified_ideal_point_positive_distance:k3:avg1m

# Cluster average
descheduler:cluster:linear_amplified_ideal_point_positive_distance:k3:avg1m

# Identify overutilized nodes
descheduler:node:linear_amplified_ideal_point_positive_distance:k3:avg1m
  > on() group_left()
  (descheduler:cluster:linear_amplified_ideal_point_positive_distance:k3:avg1m + 0.10)

# CPU and memory usage
node_cpu_usage_ratio
node_memory_usage_ratio

# Pressure metrics
node_cpu_pressure_psi
node_memory_pressure_psi
```

### Viewing VMs

```bash
# List all VMs
kubectl get vm

# Watch VM status changes
kubectl get vm -w

# Describe a VM
kubectl describe vm <vm-name>

# View VM details with node assignment
kubectl get vm -o wide
```

### Viewing Pods

```bash
# List virt-launcher pods
kubectl get pods -l app=virt-launcher

# Watch pod status
kubectl get pods -w

# View pod annotations (VM resource consumption)
kubectl get pod <pod-name> -o jsonpath='{.metadata.annotations}'
```

### Descheduler Logs

```bash
# Follow descheduler logs
kubectl logs -n kube-descheduler deployment/descheduler -f

# View recent evictions
kubectl logs -n kube-descheduler deployment/descheduler | grep -i evict
```

## Testing

```bash
# Run automated test suite
./test-closed-loop.sh

# Manual health checks
curl http://localhost:9090/-/healthy  # Prometheus
curl http://localhost:8001/health     # Metrics Exporter

# Check metrics are being scraped
curl http://localhost:9090/api/v1/targets

# Check recording rules
curl http://localhost:9090/api/v1/rules
```

## Troubleshooting

### Descheduler Not Evicting Pods

1. Check if nodes have the required label:
```bash
kubectl get nodes -l kubevirt.io/schedulable=true
```

2. Check descheduler logs for errors:
```bash
kubectl logs -n kube-descheduler deployment/descheduler
```

3. Verify Prometheus metrics are available:
```bash
curl "http://localhost:9090/api/v1/query?query=descheduler:node:linear_amplified_ideal_point_positive_distance:k3:avg1m"
```

### Evictions Not Triggering Migrations

1. Check eviction webhook is running:
```bash
kubectl get pods -l app=eviction-webhook
```

2. View webhook logs:
```bash
kubectl logs -l app=eviction-webhook -f
```

3. Check VM controller is running:
```bash
kubectl get pods -l app=vm-controller
```

### Metrics Not Updating

1. Check metrics exporter is running:
```bash
kubectl get pods -n monitoring -l app=metrics-exporter
```

2. View exporter logs:
```bash
kubectl logs -n monitoring -l app=metrics-exporter
```

3. Check Prometheus is scraping:
```bash
curl http://localhost:9090/api/v1/targets
```

## Container Runtime Support

### Docker (Default)
```bash
./setup-kind-env.sh  # Auto-detects Docker
```

### Podman
```bash
# Auto-detection (uses Podman if Docker not available)
./setup-kind-env.sh

# Force Podman
export KIND_EXPERIMENTAL_PROVIDER=podman
./setup-kind-env.sh
```

See [PODMAN_SETUP.md](PODMAN_SETUP.md) for detailed Podman configuration.

## Cleanup

```bash
# Delete cluster
kind delete cluster --name node-classifier-sim

# Clean containers (Docker)
docker system prune -a

# Clean containers (Podman)
podman system prune -a
```

## Requirements

- **Container Runtime**: Docker or Podman
- **KIND**: v0.30.0+ recommended (v0.20.0+ minimum for Podman support)
- **Kubernetes**: v1.34.0 (configured automatically by KIND)
- **kubectl**: Latest stable (compatible with K8s 1.34)
- **Python**: 3.11+
- **jq**: For test scripts

## Documentation

| File | Description |
|------|-------------|
| [SCENARIO_GUIDE.md](SCENARIO_GUIDE.md) | Complete guide to creating dynamic workload scenarios |
| [PROMETHEUS_ALGORITHMS.md](PROMETHEUS_ALGORITHMS.md) | All 19 algorithms with PromQL implementations |
| [QUICKSTART.md](QUICKSTART.md) | Quick reference guide |
| [PODMAN_SETUP.md](PODMAN_SETUP.md) | Podman-specific configuration |
| [README_PODS.md](README_PODS.md) | Pod-based VM simulation architecture |
| [README_VM_CRD.md](README_VM_CRD.md) | VirtualMachine CRD specification |
| [RESOURCE_MODEL.md](RESOURCE_MODEL.md) | Resource consumption model |
| [SCHEDULER_INTEGRATION.md](SCHEDULER_INTEGRATION.md) | Kubernetes scheduler integration |

## Contributing

This is a testing/simulation environment for the Kubernetes Descheduler. The descheduler itself is maintained upstream:
- **Descheduler**: https://github.com/kubernetes-sigs/descheduler
- **OpenShift Descheduler**: https://github.com/openshift/descheduler

## License

[Include your license here]
