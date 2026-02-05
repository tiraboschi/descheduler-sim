# Quick Start Guide - Closed-Loop Simulation

## TL;DR

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set up KIND cluster with Prometheus
./setup-kind-env.sh

# 3. Test the setup
./test-closed-loop.sh

# 4. Watch the descheduler in action
kubectl logs -n kube-descheduler deployment/descheduler -f
```

## What You Get

A complete closed-loop testing environment with:
- **5 KWOK nodes** (fake Kubernetes nodes)
- **VirtualMachine CRD** (KubeVirt-like VM resources)
- **Prometheus** with recording rules for 19 algorithms
- **Kubernetes Descheduler** with Prometheus integration
- **Eviction Webhook** for VM migration on pod eviction
- **Synthetic metrics exporter** that reads pod annotations

## Architecture Flow

```
1. Metrics Exporter reads pod annotations and calculates node metrics
   ↓
2. Prometheus scrapes metrics every 15s
   ↓
3. Prometheus recording rules calculate algorithm scores
   ↓
4. Descheduler queries Prometheus for node scores
   ↓
5. Descheduler evicts pods from overutilized nodes
   ↓
6. Eviction Webhook intercepts evictions and triggers VM migrations
   ↓
7. VM Controller deletes old pod and creates new pod
   ↓
8. Kubernetes Scheduler places new pod on available node
   ↓
9. Metrics Exporter recalculates metrics from new pod locations
   ↓
10. Go to step 2 (closed loop!)
```

## Key Files

| File | Purpose |
|------|---------|
| `prometheus_exporter.py` | Flask app exposing node metrics from pod annotations |
| `eviction_webhook.py` | Intercepts pod evictions from descheduler |
| `vm_controller.py` | Manages VirtualMachine CR lifecycle |
| `pod_manager.py` | Manages virt-launcher pod lifecycle |
| `setup-kind-env.sh` | Automated KIND cluster setup |
| `test-closed-loop.sh` | Test suite |

## Usage Examples

### Monitor Descheduler

```bash
# Follow descheduler logs
kubectl logs -n kube-descheduler deployment/descheduler -f

# View recent evictions
kubectl logs -n kube-descheduler deployment/descheduler | grep -i evict
```

### Watch VM Migrations

```bash
# Watch VirtualMachine status changes
kubectl get vm -w

# Watch pod status
kubectl get pods -w

# View all VMs with their current nodes
kubectl get vm -o wide
```

### Switch Algorithms

Edit `k8s/descheduler-policy.yaml` and change the Prometheus query:

```yaml
metricsUtilization:
  prometheus:
    # Change this to use a different algorithm
    query: descheduler:node:euclidean_distance:avg1m
  source: Prometheus
```

Then apply:
```bash
kubectl apply -f k8s/descheduler-policy.yaml
kubectl rollout restart -n kube-descheduler deployment/descheduler
```

### Available Algorithms

All algorithms are available as Prometheus recording rules:
- `descheduler:node:weighted_average:avg1m`
- `descheduler:node:euclidean_distance:avg1m`
- `descheduler:node:ideal_point_positive_distance:avg1m`
- `descheduler:node:linear_amplified_ippd_k3:avg1m`
- And 15 more...

See [PROMETHEUS_ALGORITHMS.md](PROMETHEUS_ALGORITHMS.md) for the complete list.

## Accessing Services

| Service | URL | Purpose |
|---------|-----|---------|
| Prometheus | http://localhost:9090 | Query metrics, view recording rules |
| Metrics Exporter | http://localhost:8001/metrics | View raw metrics |
| Exporter Health | http://localhost:8001/health | Check exporter status |
| Exporter State | http://localhost:8001/scenario | View current node state |

## Working with VirtualMachines

The VirtualMachine CRD is automatically installed by `setup-kind-env.sh`:

```bash
# List VMs
kubectl get vm

# Create example VMs
kubectl apply -f k8s/example-vms.yaml

# Describe a VM
kubectl describe vm vm-small-1

# View VM details
kubectl get vm -o wide

# Watch VM status changes
kubectl get vm -w
```

VMs show:
- **Allocated resources** (CPU cores, memory)
- **Utilization** (what VM is actually using)
- **Pod name** (virt-launcher pod executing the VM)
- **Node** (where scheduler placed it)

See [README_VM_CRD.md](README_VM_CRD.md) and [RESOURCE_MODEL.md](RESOURCE_MODEL.md) for details.

## Useful PromQL Queries

Visit http://localhost:9090/graph and try:

```promql
# Current CPU usage by node
descheduler:node:cpu_usage:ratio

# Nodes with high pressure
descheduler:node:cpu_pressure:psi > 0.5 or descheduler:node:memory_pressure:psi > 0.5

# Cluster average CPU
descheduler:cluster:cpu_usage:avg

# Algorithm scores (example: Ideal Point Positive Distance)
descheduler:node:ideal_point_positive_distance:score

# Linear Amplified IPPD (k=3.0)
descheduler:node:linear_amplified_ippd_k3:score
```

## Troubleshooting

### Metrics not showing up

```bash
# Check exporter is running
kubectl get pods -n monitoring

# Check exporter logs
kubectl logs -n monitoring -l app=metrics-exporter

# Check Prometheus targets
# Visit: http://localhost:9090/targets
```

### Simulation fails to connect

```bash
# Test connectivity
curl http://localhost:9090/-/healthy
curl http://localhost:8001/health

# Port forward manually if needed
kubectl port-forward -n monitoring svc/prometheus 9090:9090
kubectl port-forward -n monitoring svc/metrics-exporter 8001:8000
```

### Recording rules not working

```bash
# Check PrometheusRule
kubectl get prometheusrules -n monitoring

# View in Prometheus UI
# Visit: http://localhost:9090/rules
```

## Cleanup

```bash
# Delete KIND cluster
kind delete cluster --name node-classifier-sim
```

## Next Steps

1. **Benchmark algorithms**: Run different algorithms on the same scenario
2. **Add more nodes**: Edit `k8s/kwok-nodes.yaml`
3. **Custom metrics**: Modify `prometheus_exporter.py`
4. **Grafana dashboards**: Add Grafana to visualize results
5. **Real descheduler**: Integrate with actual K8s descheduler

## Full Documentation

- [README.md](README.md) - Complete Prometheus integration guide
- [PROMETHEUS_ALGORITHMS.md](PROMETHEUS_ALGORITHMS.md) - Algorithm implementation in PromQL
- [PODMAN_SETUP.md](PODMAN_SETUP.md) - Podman-specific setup
- [README_PODS.md](README_PODS.md) - Pod-based VM simulation with KWOK
- [README_VM_CRD.md](README_VM_CRD.md) - VirtualMachine Custom Resource Definition
- [RESOURCE_MODEL.md](RESOURCE_MODEL.md) - Resource model documentation
- [SCHEDULER_INTEGRATION.md](SCHEDULER_INTEGRATION.md) - Scheduler integration guide