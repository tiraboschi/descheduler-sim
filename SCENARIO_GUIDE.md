# SimulationScenario Guide

This guide explains how to use SimulationScenarios to create dynamic, realistic workload patterns for testing the descheduler.

## Table of Contents

- [Overview](#overview)
- [Quick Start](#quick-start)
- [Scenario Structure](#scenario-structure)
- [Node Selection](#node-selection)
- [Task Types](#task-types)
- [Task Generators](#task-generators)
- [Examples](#examples)
- [Advanced Features](#advanced-features)

## Overview

SimulationScenarios allow you to create complex, dynamic workload patterns that:

- **Target specific nodes**: Generate load on the most/least loaded nodes
- **Use stochastic processes**: Model realistic traffic with Poisson distributions
- **Create dynamic workloads**: Tasks with varying CPU/memory consumption and duration
- **Scheduled events**: Apply load patterns according to a timeline

This enables realistic testing of the descheduler's behavior under various load conditions.

**Important Note**: The `timeScale` parameter only affects how fast the scenario controller plays through its schedule - it does NOT affect Prometheus scrape intervals, recording rule evaluation, or descheduler timing. All monitoring and descheduling still operates on real time.

## Quick Start

1. **Apply a scenario**:
   ```bash
   kubectl apply -f k8s/example-scenario-simple.yaml
   ```

2. **Watch the scenario execute**:
   ```bash
   kubectl get scenarios -w
   kubectl logs -l app=scenario-controller -f
   ```

3. **Check VM utilization changes**:
   ```bash
   kubectl get vm -w
   ```

4. **Monitor descheduler response**:
   ```bash
   kubectl logs -n kube-descheduler deployment/descheduler -f
   ```

## Scenario Structure

A SimulationScenario has the following main components:

```yaml
apiVersion: simulation.node-classifier.io/v1alpha1
kind: SimulationScenario
metadata:
  name: my-scenario
spec:
  # How long to run (simulated time)
  duration: 24h

  # Time acceleration (60 = 1 real min = 1 sim hour)
  timeScale: 60.0

  # Define groups of VMs
  vmPools:
    workers:
      vms: [vm-small-1, vm-medium-1]

  # Define dynamic node selection
  nodeSelectors:
    most-loaded:
      type: dynamic
      strategy: maxMetric
      metric: cpu_usage

  # Define types of tasks
  taskTypes:
    heavy-load:
      resources:
        cpu: {min: 0.40, max: 0.80}
        memory: {min: 0.30, max: 0.60}
      duration: {min: 300, max: 900}

  # Generate tasks over time
  taskGenerators:
    - name: stress-test
      schedule:
        type: periodic
        interval: 5m
      assignment:
        strategy: nodeAware
        nodeSelector: most-loaded
      taskType: heavy-load
      rate: {value: 1}
```

## Node Selection

Node selectors allow you to dynamically target specific nodes based on their current state.

### Static Selection

Select nodes by name or labels:

```yaml
nodeSelectors:
  production-nodes:
    type: static
    names: [kwok-node-1, kwok-node-2]
    # OR
    labels:
      env: production
```

### Dynamic Selection

Select nodes based on current metrics:

```yaml
nodeSelectors:
  most-loaded:
    type: dynamic
    strategy: maxMetric  # or minMetric
    metric: cpu_usage    # or memory_usage, cpu_pressure, etc.
    count: 2             # Select top/bottom N nodes (default: 1)

  overloaded:
    type: dynamic
    strategy: threshold
    metric: cpu_usage
    condition: ">"
    value: 0.8
```

Available metrics:
- `cpu_usage`: Current CPU utilization (0.0-1.0)
- `memory_usage`: Current memory utilization (0.0-1.0)
- `cpu_pressure`: CPU pressure metric
- `memory_pressure`: Memory pressure metric

### Random Selection

Select random nodes:

```yaml
nodeSelectors:
  random-nodes:
    type: random
    count: 3
    labels:              # Optional: filter by labels first
      type: kwok
```

## Task Types

Task types define the resource consumption and duration characteristics of workloads.

### Resource Distribution

Define how CPU and memory are sampled:

```yaml
taskTypes:
  user-request:
    resources:
      cpu:
        min: 0.05
        max: 0.20
        distribution: normal  # uniform, normal, exponential
        mean: 0.10            # For normal distribution
        stddev: 0.03          # For normal distribution
      memory:
        min: 0.03
        max: 0.10
        distribution: uniform
```

### Duration Distribution

Define how long tasks run:

```yaml
taskTypes:
  batch-job:
    duration:
      min: 300          # 5 minutes (in simulated seconds)
      max: 1800         # 30 minutes
      mean: 900         # 15 minutes
      distribution: exponential
```

Distribution types:
- `uniform`: Equal probability across min-max range
- `normal`: Bell curve around mean with stddev
- `exponential`: Decay with lambda=1/mean

## Task Generators

Task generators create tasks over time according to a schedule and assignment strategy.

### Schedule Types

**Periodic**: Run at regular intervals

```yaml
taskGenerators:
  - name: regular-traffic
    schedule:
      type: periodic
      interval: 30s      # Every 30 seconds (simulated time)
```

**One-time**: Run once at a specific time

```yaml
taskGenerators:
  - name: batch-job
    schedule:
      type: once
      time: 2h           # 2 hours into simulation
```

### Assignment Strategies

**Random**: Assign to random VMs from a pool

```yaml
assignment:
  strategy: random
  pool: workers        # VM pool name
```

**Node-Aware**: Target VMs on specific nodes

```yaml
assignment:
  strategy: nodeAware
  nodeSelector: most-loaded
  vmSelection:
    count: {min: 1, max: 3}
    strategy: random   # or first, all
```

### Task Rate

Control how many tasks are created per interval:

**Fixed rate**:
```yaml
rate:
  value: 5             # Exactly 5 tasks
```

**Poisson distribution** (realistic traffic):
```yaml
rate:
  lambda: 3            # Average 3 tasks, follows Poisson distribution
  distribution: poisson
```

## Examples

### Example 1: Simple Periodic Workload

Generate steady user traffic with realistic randomness:

```yaml
apiVersion: simulation.node-classifier.io/v1alpha1
kind: SimulationScenario
metadata:
  name: simple-workload
spec:
  duration: 10m
  timeScale: 1.0

  vmPools:
    workers:
      vms: [vm-small-1, vm-medium-1, vm-large-1]

  taskTypes:
    user-request:
      resources:
        cpu: {min: 0.05, max: 0.20, distribution: normal, mean: 0.10, stddev: 0.03}
        memory: {min: 0.03, max: 0.10, distribution: normal, mean: 0.06, stddev: 0.02}
      duration: {min: 30, max: 300, mean: 120, distribution: exponential}

  taskGenerators:
    - name: user-traffic
      schedule:
        type: periodic
        interval: 30s
      assignment:
        strategy: random
        pool: workers
      taskType: user-request
      rate: {lambda: 3, distribution: poisson}
```

This creates realistic user traffic where:
- Tasks arrive following a Poisson process (average 3 per 30s)
- CPU/memory consumption varies normally around typical values
- Duration follows exponential decay (most tasks are short, some are long)

### Example 2: Stress Hot Nodes

Amplify load on already-busy nodes to trigger descheduling:

```yaml
apiVersion: simulation.node-classifier.io/v1alpha1
kind: SimulationScenario
metadata:
  name: stress-hot-nodes
spec:
  duration: 30m
  timeScale: 1.0

  nodeSelectors:
    most-loaded:
      type: dynamic
      strategy: maxMetric
      metric: cpu_usage

    least-loaded:
      type: dynamic
      strategy: minMetric
      metric: cpu_usage

  taskTypes:
    heavy-load:
      resources:
        cpu: {min: 0.40, max: 0.80, distribution: uniform}
        memory: {min: 0.30, max: 0.60, distribution: uniform}
      duration: {min: 300, max: 900, mean: 600}

    light-load:
      resources:
        cpu: {min: 0.05, max: 0.15, distribution: uniform}
        memory: {min: 0.05, max: 0.15, distribution: uniform}
      duration: {min: 60, max: 180, mean: 120}

  taskGenerators:
    - name: amplify-hotspot
      enabled: true
      schedule:
        type: periodic
        interval: 5m
      assignment:
        strategy: nodeAware
        nodeSelector: most-loaded
        vmSelection:
          count: {min: 1, max: 2, distribution: uniform}
          strategy: random
      taskType: heavy-load
      rate: {value: 1}

    - name: baseline-for-idle
      enabled: true
      schedule:
        type: periodic
        interval: 2m
      assignment:
        strategy: nodeAware
        nodeSelector: least-loaded
        vmSelection:
          count: {value: 1}
          strategy: random
      taskType: light-load
      rate: {lambda: 2, distribution: poisson}
```

This scenario:
- Adds heavy load to the most loaded node every 5 minutes
- Keeps idle nodes from being completely empty
- Creates imbalance to test descheduler effectiveness

### Example 3: Traffic Variation Pattern

Demonstrate varying load levels (could model business hours/off-hours):

```yaml
apiVersion: simulation.node-classifier.io/v1alpha1
kind: SimulationScenario
metadata:
  name: traffic-variation
spec:
  duration: 20m
  timeScale: 1.0

  vmPools:
    all-vms:
      selector:
        matchLabels:
          type: workload

  taskTypes:
    high-traffic:
      resources:
        cpu: {min: 0.10, max: 0.40, distribution: normal, mean: 0.20, stddev: 0.08}
        memory: {min: 0.10, max: 0.30, distribution: normal, mean: 0.15, stddev: 0.05}
      duration: {min: 60, max: 600, mean: 180, distribution: exponential}

    low-traffic:
      resources:
        cpu: {min: 0.02, max: 0.10, distribution: normal, mean: 0.05, stddev: 0.02}
        memory: {min: 0.02, max: 0.08, distribution: normal, mean: 0.04, stddev: 0.02}
      duration: {min: 120, max: 1200, mean: 300, distribution: exponential}

  taskGenerators:
    # High traffic period (first 10 minutes)
    - name: high-traffic-period
      schedule:
        type: periodic
        interval: 1m
      assignment:
        strategy: random
        pool: all-vms
      taskType: high-traffic
      rate: {lambda: 10, distribution: poisson}

    # Low traffic period (runs throughout)
    - name: low-traffic-period
      schedule:
        type: periodic
        interval: 5m
      assignment:
        strategy: random
        pool: all-vms
      taskType: low-traffic
      rate: {lambda: 2, distribution: poisson}
```

## Advanced Features

### Schedule Playback Speed (timeScale)

The `timeScale` parameter controls how fast the scenario controller plays through its schedule:

- `timeScale: 1.0` - Real-time playback (default, recommended)
- `timeScale: 60.0` - Play 60x faster (a 1-hour schedule takes 1 minute)

**Important Limitations**: This only speeds up the scenario controller's event generation. It does NOT affect:
- Prometheus scrape intervals (still every 15s real time)
- Recording rule evaluation (still every 15s real time)
- Descheduler polling (still every 60s real time)
- Metric aggregation windows (e.g., `avg_over_time[1m]` is still 1 real minute)

**Recommendation**: Use `timeScale: 1.0` (real-time) for most testing. Higher values can rapidly cycle through load patterns but won't produce realistic metric aggregations.

### VM Pool Selection

Define reusable VM groups:

**By explicit list**:
```yaml
vmPools:
  critical:
    vms: [vm-db-1, vm-cache-1]
```

**By label selector**:
```yaml
vmPools:
  production:
    selector:
      matchLabels:
        env: production
        tier: frontend
```

### Monitoring Scenario Progress

Check scenario status:

```bash
# List all scenarios
kubectl get scenarios

# Get detailed status
kubectl describe scenario my-scenario

# Watch scenario progress
kubectl get scenario my-scenario -o yaml -w
```

The status shows:
- `phase`: Pending, Running, Paused, Completed, Failed
- `currentSimulatedTime`: Where we are in simulation time
- `elapsedRealTime`: How long the scenario has been running
- `totalTasksGenerated`: Number of tasks created so far

### Debugging

View controller logs:

```bash
# Watch scenario controller
kubectl logs -l app=scenario-controller -f

# Check specific scenario execution
kubectl logs -l app=scenario-controller --tail=100 | grep "my-scenario"
```

Common issues:
- **No VMs matching pool**: Check `kubectl get vm` and verify VM names
- **No nodes matching selector**: Check node metrics with Prometheus
- **Tasks not appearing**: Verify VM controller is running

## Best Practices

1. **Start simple**: Test with short scenarios first (duration: 10m, timeScale: 1.0)

2. **Use realistic distributions**:
   - Poisson for arrival rates (models real traffic)
   - Normal for resource consumption (most workloads cluster around average)
   - Exponential for duration (many short tasks, few long ones)

3. **Balance load generation**:
   - Don't overwhelm VMs (sum of task rates should be reasonable)
   - Use multiple generators with different patterns

4. **Test descheduler response**:
   - Create imbalance with node-aware selection
   - Monitor when and how descheduler rebalances
   - Check eviction webhook logs for VM migrations

5. **Monitor metrics**:
   - Use Prometheus to verify utilization changes
   - Check recording rules are updating
   - Verify descheduler sees the metrics

## Next Steps

- Explore the example scenarios in `k8s/example-scenario-*.yaml`
- Create your own scenario based on your testing needs
- Combine with descheduler policy tuning to test different strategies
- Use scenarios to validate descheduler behavior under various conditions
