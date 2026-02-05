#!/usr/bin/env python3
"""
Simulation Scenario Controller

Watches SimulationScenario CRs and executes them by:
- Managing timeline events
- Running task generators
- Evaluating conditional events
- Updating VM utilization dynamically
"""

import time
import logging
import threading
import random
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from collections import defaultdict
import re

from kubernetes import client, config, watch
from kubernetes.client.rest import ApiException

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def parse_duration(duration_str: str) -> timedelta:
    """Parse duration string like '24h', '7d', '30m' into timedelta."""
    match = re.match(r'(\d+)([smhd])', duration_str)
    if not match:
        raise ValueError(f"Invalid duration format: {duration_str}")

    value, unit = int(match.group(1)), match.group(2)
    if unit == 's':
        return timedelta(seconds=value)
    elif unit == 'm':
        return timedelta(minutes=value)
    elif unit == 'h':
        return timedelta(hours=value)
    elif unit == 'd':
        return timedelta(days=value)


def parse_time(time_str: str) -> Optional[timedelta]:
    """Parse time string like 'HH:MM' or '+2h' into timedelta from start."""
    if time_str.startswith('+'):
        return parse_duration(time_str[1:])

    # Parse HH:MM format
    match = re.match(r'(\d{1,2}):(\d{2})', time_str)
    if match:
        hours, minutes = int(match.group(1)), int(match.group(2))
        return timedelta(hours=hours, minutes=minutes)

    return None


def sample_from_distribution(config: Dict[str, Any]) -> float:
    """Sample a value from a distribution specification."""
    if 'value' in config:
        return float(config['value'])

    dist_type = config.get('distribution', 'uniform')
    min_val = float(config.get('min', 0))
    max_val = float(config.get('max', 1))

    if dist_type == 'uniform':
        return random.uniform(min_val, max_val)
    elif dist_type == 'normal':
        mean = float(config.get('mean', (min_val + max_val) / 2))
        stddev = float(config.get('stddev', (max_val - min_val) / 6))
        value = random.gauss(mean, stddev)
        return max(min_val, min(max_val, value))
    elif dist_type == 'exponential':
        mean = float(config.get('mean', (min_val + max_val) / 2))
        value = random.expovariate(1.0 / mean)
        return max(min_val, min(max_val, value))
    elif dist_type == 'poisson':
        lambda_val = float(config.get('lambda', 1.0))
        return min(max_val, random.poisson(lambda_val))

    return min_val


@dataclass
class ActiveTask:
    """Represents an active task running on a VM."""
    vm_id: str
    cpu: float
    memory: float
    end_time: datetime
    description: str = ""


class NodeSelector:
    """Handles node selection based on various strategies."""

    def __init__(self, k8s_api: client.CoreV1Api, custom_api: client.CustomObjectsApi):
        self.k8s_api = k8s_api
        self.custom_api = custom_api

    def select_nodes(self, selector_config: Dict[str, Any], namespace: str = "default") -> List[str]:
        """Select nodes based on selector configuration."""
        selector_type = selector_config.get('type', 'static')

        if selector_type == 'static':
            return self._select_static(selector_config)
        elif selector_type == 'dynamic':
            return self._select_dynamic(selector_config, namespace)
        elif selector_type == 'random':
            return self._select_random(selector_config)
        else:
            logger.warning(f"Unknown selector type: {selector_type}")
            return []

    def _select_static(self, config: Dict[str, Any]) -> List[str]:
        """Select nodes by name or labels."""
        if 'nodeName' in config:
            return [config['nodeName']]

        if 'matchLabels' in config:
            label_selector = ','.join([f"{k}={v}" for k, v in config['matchLabels'].items()])
            nodes = self.k8s_api.list_node(label_selector=label_selector)
            return [node.metadata.name for node in nodes.items]

        return []

    def _select_dynamic(self, config: Dict[str, Any], namespace: str) -> List[str]:
        """Select nodes dynamically based on metrics."""
        strategy = config.get('strategy')
        metric = config.get('metric', 'cpu_usage')

        # Get all KWOK nodes
        nodes = self.k8s_api.list_node(label_selector="type=kwok")
        node_metrics = {}

        # Collect metrics for each node
        for node in nodes.items:
            node_name = node.metadata.name
            metric_value = self._get_node_metric(node_name, metric, namespace)
            if metric_value is not None:
                node_metrics[node_name] = metric_value

        if not node_metrics:
            return []

        if strategy == 'maxMetric':
            max_node = max(node_metrics.items(), key=lambda x: x[1])
            return [max_node[0]]
        elif strategy == 'minMetric':
            min_node = min(node_metrics.items(), key=lambda x: x[1])
            return [min_node[0]]
        elif strategy == 'threshold':
            operator = config.get('operator', '>')
            threshold = float(config.get('value', 0.5))

            if operator == '>':
                return [node for node, value in node_metrics.items() if value > threshold]
            elif operator == '<':
                return [node for node, value in node_metrics.items() if value < threshold]
            elif operator == '>=':
                return [node for node, value in node_metrics.items() if value >= threshold]
            elif operator == '<=':
                return [node for node, value in node_metrics.items() if value <= threshold]

        return []

    def _select_random(self, config: Dict[str, Any]) -> List[str]:
        """Select random node(s)."""
        nodes = self.k8s_api.list_node(label_selector="type=kwok")
        node_names = [node.metadata.name for node in nodes.items]

        count = config.get('count', 1)
        if count >= len(node_names):
            return node_names

        return random.sample(node_names, count)

    def _get_node_metric(self, node_name: str, metric: str, namespace: str) -> Optional[float]:
        """Get current metric value for a node."""
        # Get all virt-launcher pods on this node
        try:
            pods = self.k8s_api.list_namespaced_pod(
                namespace=namespace,
                label_selector="app=virt-launcher",
                field_selector=f"spec.nodeName={node_name}"
            )

            # Sum up resource consumption from pod annotations
            total_cpu = 0.0
            total_memory = 0.0

            for pod in pods.items:
                annotations = pod.metadata.annotations or {}
                cpu = float(annotations.get('vm.simulation.io/cpu-consumption', 0))
                memory = float(annotations.get('vm.simulation.io/memory-consumption', 0))
                total_cpu += cpu
                total_memory += memory

            if metric == 'cpu_usage':
                return total_cpu
            elif metric == 'memory_usage':
                return total_memory
            # TODO: Add support for pressure metrics and descheduler scores

        except ApiException as e:
            logger.error(f"Error getting metrics for node {node_name}: {e}")

        return None


class ScenarioExecutor:
    """Executes a simulation scenario."""

    def __init__(self, scenario_name: str, scenario_spec: Dict[str, Any], namespace: str = "default"):
        self.scenario_name = scenario_name
        self.spec = scenario_spec
        self.namespace = namespace

        # Kubernetes clients
        try:
            config.load_incluster_config()
        except:
            config.load_kube_config()

        self.k8s_api = client.CoreV1Api()
        self.custom_api = client.CustomObjectsApi()
        self.node_selector = NodeSelector(self.k8s_api, self.custom_api)

        # Simulation state
        self.start_time = datetime.now()
        self.time_scale = float(self.spec.get('timeScale', 1.0))
        self.duration = parse_duration(self.spec.get('duration', '24h'))
        self.running = False
        self.paused = False

        # Active tasks (VM -> list of active tasks)
        self.active_tasks: Dict[str, List[ActiveTask]] = defaultdict(list)

        # Statistics
        self.total_tasks_generated = 0

        logger.info(f"Initialized scenario '{scenario_name}' - Duration: {self.duration}, TimeScale: {self.time_scale}x")

    def get_simulated_time(self) -> datetime:
        """Get current simulated time."""
        elapsed_real = datetime.now() - self.start_time
        elapsed_sim = elapsed_real * self.time_scale
        return self.start_time + elapsed_sim

    def get_elapsed_simulated_time(self) -> timedelta:
        """Get elapsed simulated time."""
        elapsed_real = datetime.now() - self.start_time
        return elapsed_real * self.time_scale

    def is_complete(self) -> bool:
        """Check if scenario is complete."""
        return self.get_elapsed_simulated_time() >= self.duration

    def update_status(self, phase: str, message: str = ""):
        """Update scenario status in Kubernetes."""
        try:
            sim_time = self.get_simulated_time()
            elapsed_sim = self.get_elapsed_simulated_time()
            elapsed_real = datetime.now() - self.start_time

            status = {
                'phase': phase,
                'currentSimulatedTime': sim_time.isoformat(),
                'elapsedSimulatedTime': str(elapsed_sim),
                'elapsedRealTime': str(elapsed_real),
                'totalTasksGenerated': self.total_tasks_generated,
                'message': message
            }

            if phase == 'Completed':
                status['endTime'] = datetime.now().isoformat()

            self.custom_api.patch_namespaced_custom_object_status(
                group="simulation.node-classifier.io",
                version="v1alpha1",
                namespace=self.namespace,
                plural="simulationscenarios",
                name=self.scenario_name,
                body={'status': status}
            )
        except ApiException as e:
            logger.error(f"Failed to update status: {e}")

    def run(self):
        """Main execution loop."""
        logger.info(f"Starting scenario execution: {self.scenario_name}")
        self.running = True
        self.update_status('Running', 'Scenario started')

        try:
            # Start task generator threads
            generator_threads = []
            for gen_config in self.spec.get('taskGenerators', []):
                if gen_config.get('enabled', True):
                    t = threading.Thread(target=self._run_task_generator, args=(gen_config,), daemon=True)
                    t.start()
                    generator_threads.append(t)

            # Main simulation loop
            while self.running and not self.is_complete():
                if not self.paused:
                    # Clean up completed tasks
                    self._cleanup_completed_tasks()

                    # Check timeline events
                    self._check_timeline_events()

                    # Check conditional events
                    self._check_conditional_events()

                    # Update status periodically
                    if int(time.time()) % 10 == 0:
                        self.update_status('Running', f'Simulated time: {self.get_simulated_time().strftime("%H:%M:%S")}')

                time.sleep(1)  # Real time sleep

            # Scenario completed
            self.running = False
            self.update_status('Completed', 'Scenario execution finished')
            logger.info(f"Scenario '{self.scenario_name}' completed")

        except Exception as e:
            logger.error(f"Scenario execution failed: {e}", exc_info=True)
            self.update_status('Failed', str(e))
            self.running = False

    def _run_task_generator(self, gen_config: Dict[str, Any]):
        """Run a task generator in a separate thread."""
        gen_name = gen_config.get('name', 'unnamed')
        logger.info(f"Started task generator: {gen_name}")

        schedule_type = gen_config.get('schedule', {}).get('type', 'periodic')
        interval_str = gen_config.get('schedule', {}).get('interval', '1m')
        interval = parse_duration(interval_str)

        while self.running and not self.is_complete():
            if self.paused:
                time.sleep(1)
                continue

            # Check if we're in an active window
            if not self._is_in_active_window(gen_config):
                time.sleep(1)
                continue

            # Generate tasks
            try:
                self._generate_tasks(gen_config)
            except Exception as e:
                logger.error(f"Error in task generator '{gen_name}': {e}", exc_info=True)

            # Sleep for interval (adjusted for time scale)
            sleep_time = interval.total_seconds() / self.time_scale
            time.sleep(sleep_time)

        logger.info(f"Stopped task generator: {gen_name}")

    def _is_in_active_window(self, gen_config: Dict[str, Any]) -> bool:
        """Check if current simulated time is in an active window."""
        windows = gen_config.get('schedule', {}).get('activeWindows', [])
        if not windows:
            return True  # No windows = always active

        sim_time = self.get_simulated_time()
        current_hm = sim_time.strftime("%H:%M")

        for window in windows:
            start = window.get('start', '00:00')
            end = window.get('end', '23:59')

            if start <= current_hm <= end:
                # TODO: Apply weight to rate
                return True

        return False

    def _generate_tasks(self, gen_config: Dict[str, Any]):
        """Generate and assign tasks based on generator configuration."""
        # Determine how many tasks to generate
        rate_config = gen_config.get('rate', {'value': 1})
        num_tasks = int(sample_from_distribution(rate_config))

        if num_tasks <= 0:
            return

        # Select target VMs
        target_vms = self._select_target_vms(gen_config)

        if not target_vms:
            logger.warning(f"No target VMs found for generator {gen_config.get('name')}")
            return

        # Get task type
        task_type_name = gen_config.get('taskType')
        task_type = self.spec.get('taskTypes', {}).get(task_type_name, {})

        # Generate and assign tasks
        for _ in range(num_tasks):
            # Sample task parameters
            cpu = sample_from_distribution(task_type.get('resources', {}).get('cpu', {'value': 0.1}))
            memory = sample_from_distribution(task_type.get('resources', {}).get('memory', {'value': 0.1}))
            duration = sample_from_distribution(task_type.get('duration', {'value': 60}))  # seconds

            # Pick a VM
            vm_id = random.choice(target_vms)

            # Create and assign task
            task = ActiveTask(
                vm_id=vm_id,
                cpu=cpu,
                memory=memory,
                end_time=datetime.now() + timedelta(seconds=duration / self.time_scale),
                description=f"Task from {gen_config.get('name')}"
            )

            self.active_tasks[vm_id].append(task)
            self.total_tasks_generated += 1

            # Update VM utilization immediately
            self._update_vm_utilization(vm_id)

            logger.debug(f"Assigned task to {vm_id}: CPU={cpu:.2f}, MEM={memory:.2f}, duration={duration}s")

    def _select_target_vms(self, config: Dict[str, Any]) -> List[str]:
        """Select target VMs based on assignment configuration."""
        assignment = config.get('assignment', {})
        strategy = assignment.get('strategy', 'random')

        if strategy == 'random':
            pool_name = assignment.get('pool')
            if pool_name:
                vm_pool = self.spec.get('vmPools', {}).get(pool_name, {})
                return vm_pool.get('vms', [])

        elif strategy == 'nodeAware':
            node_selector_config = assignment.get('nodeSelector', {})
            nodes = self.node_selector.select_nodes(node_selector_config, self.namespace)

            # Get VMs on selected nodes
            target_vms = []
            for node in nodes:
                vms_on_node = self._get_vms_on_node(node)

                # Apply VM selection
                vm_selection = assignment.get('vmSelection', {})
                count_config = vm_selection.get('count', {'value': 1})
                count = int(sample_from_distribution(count_config))

                if vms_on_node:
                    selected = random.sample(vms_on_node, min(count, len(vms_on_node)))
                    target_vms.extend(selected)

            return target_vms

        return []

    def _get_vms_on_node(self, node_name: str) -> List[str]:
        """Get list of VM IDs on a specific node."""
        try:
            vms = self.custom_api.list_namespaced_custom_object(
                group="simulation.node-classifier.io",
                version="v1alpha1",
                namespace=self.namespace,
                plural="virtualmachines"
            )

            result = []
            for vm in vms.get('items', []):
                status = vm.get('status', {})
                if status.get('nodeName') == node_name:
                    result.append(vm['metadata']['name'])

            return result
        except ApiException as e:
            logger.error(f"Error getting VMs on node {node_name}: {e}")
            return []

    def _update_vm_utilization(self, vm_id: str):
        """Update VM utilization based on active tasks."""
        tasks = self.active_tasks.get(vm_id, [])

        # Sum up all active tasks
        total_cpu = sum(task.cpu for task in tasks)
        total_memory = sum(task.memory for task in tasks)

        # Update VM CR
        try:
            vm = self.custom_api.get_namespaced_custom_object(
                group="simulation.node-classifier.io",
                version="v1alpha1",
                namespace=self.namespace,
                plural="virtualmachines",
                name=vm_id
            )

            # Update utilization in spec
            if 'spec' not in vm:
                vm['spec'] = {}
            if 'utilization' not in vm['spec']:
                vm['spec']['utilization'] = {}

            vm['spec']['utilization']['cpu'] = str(min(1.0, total_cpu))
            vm['spec']['utilization']['memory'] = str(min(1.0, total_memory))

            self.custom_api.patch_namespaced_custom_object(
                group="simulation.node-classifier.io",
                version="v1alpha1",
                namespace=self.namespace,
                plural="virtualmachines",
                name=vm_id,
                body=vm
            )

            logger.debug(f"Updated {vm_id} utilization: CPU={total_cpu:.2f}, MEM={total_memory:.2f}")

        except ApiException as e:
            logger.error(f"Failed to update VM {vm_id}: {e}")

    def _cleanup_completed_tasks(self):
        """Remove completed tasks and update VM utilization."""
        now = datetime.now()

        for vm_id, tasks in list(self.active_tasks.items()):
            # Remove completed tasks
            active = [t for t in tasks if t.end_time > now]

            if len(active) != len(tasks):
                # Tasks completed, update utilization
                self.active_tasks[vm_id] = active
                self._update_vm_utilization(vm_id)

    def _check_timeline_events(self):
        """Check and execute timeline events."""
        # TODO: Implement timeline event execution
        pass

    def _check_conditional_events(self):
        """Check and execute conditional events."""
        # TODO: Implement conditional event checking
        pass


class ScenarioController:
    """Main controller that watches SimulationScenario CRs."""

    def __init__(self, namespace: str = "default"):
        self.namespace = namespace

        try:
            config.load_incluster_config()
        except:
            config.load_kube_config()

        self.custom_api = client.CustomObjectsApi()
        self.executors: Dict[str, ScenarioExecutor] = {}

    def run(self):
        """Main controller loop."""
        logger.info("Starting Simulation Scenario Controller")

        w = watch.Watch()

        try:
            for event in w.stream(
                self.custom_api.list_namespaced_custom_object,
                group="simulation.node-classifier.io",
                version="v1alpha1",
                namespace=self.namespace,
                plural="simulationscenarios"
            ):
                event_type = event['type']
                scenario = event['object']
                name = scenario['metadata']['name']

                logger.info(f"Event {event_type} for scenario {name}")

                if event_type == 'ADDED':
                    self._handle_added(name, scenario)
                elif event_type == 'MODIFIED':
                    self._handle_modified(name, scenario)
                elif event_type == 'DELETED':
                    self._handle_deleted(name)

        except Exception as e:
            logger.error(f"Controller error: {e}", exc_info=True)

    def _handle_added(self, name: str, scenario: Dict[str, Any]):
        """Handle new scenario."""
        if name in self.executors:
            logger.warning(f"Scenario {name} already exists")
            return

        spec = scenario.get('spec', {})
        executor = ScenarioExecutor(name, spec, self.namespace)
        self.executors[name] = executor

        # Start execution in a separate thread
        t = threading.Thread(target=executor.run, daemon=True)
        t.start()

        logger.info(f"Started scenario: {name}")

    def _handle_modified(self, name: str, scenario: Dict[str, Any]):
        """Handle scenario modification."""
        # For now, just log
        logger.info(f"Scenario {name} modified (restart to apply changes)")

    def _handle_deleted(self, name: str):
        """Handle scenario deletion."""
        if name in self.executors:
            executor = self.executors[name]
            executor.running = False
            del self.executors[name]
            logger.info(f"Stopped scenario: {name}")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Simulation Scenario Controller')
    parser.add_argument('--namespace', type=str, default='default', help='Kubernetes namespace')

    args = parser.parse_args()

    controller = ScenarioController(namespace=args.namespace)
    controller.run()
