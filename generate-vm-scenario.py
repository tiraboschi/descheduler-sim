#!/usr/bin/env python3
"""
Generate VirtualMachine YAML manifests from scenario_loader scenarios.

This creates VirtualMachine CRs that can be applied to Kubernetes,
which will then be picked up by the vm-controller to create virt-launcher pods.
"""

import argparse
import sys
from scenario_loader import ScenarioLoader


def node_to_vms_yaml(node, scenario_name):
    """Convert a Node with VMs into VirtualMachine YAML manifests."""
    yamls = []

    for vm in node.vms:
        # Calculate CPU cores and memory from consumption
        # Assuming 32 cores and 128Gi per KWOK node
        cpu_cores = vm.cpu_consumption * 32
        memory_gi = vm.memory_consumption * 128

        # Use CPU/memory utilization from the VM
        # For simulation: consumption = cores * utilization / 32
        # So: utilization = consumption * 32 / cores
        cpu_util = vm.cpu_utilization if hasattr(vm, 'cpu_utilization') else 0.5
        mem_util = vm.memory_utilization if hasattr(vm, 'memory_utilization') else 0.7

        yaml = f"""---
apiVersion: simulation.node-classifier.io/v1alpha1
kind: VirtualMachine
metadata:
  name: {vm.id}
  namespace: default
  labels:
    scenario: {scenario_name}
    node: {node.name}
  annotations:
    description: "From {scenario_name} scenario, originally on {node.name}"
spec:
  resources:
    cpu: "{cpu_cores:.2f}"
    memory: "{memory_gi:.2f}Gi"
  utilization:
    cpu: "{cpu_util:.2f}"
    memory: "{mem_util:.2f}"
  running: true
"""
        yamls.append(yaml)

    return yamls


def generate_scenario_yaml(scenario_name):
    """Generate VirtualMachine YAML for a scenario."""
    scenarios = ScenarioLoader.create_sample_scenarios()

    if scenario_name not in scenarios:
        print(f"Error: Scenario '{scenario_name}' not found.", file=sys.stderr)
        print(f"Available scenarios: {', '.join(scenarios.keys())}", file=sys.stderr)
        return None

    nodes = scenarios[scenario_name]
    all_yamls = []

    for node in nodes:
        yamls = node_to_vms_yaml(node, scenario_name)
        all_yamls.extend(yamls)

    return '\n'.join(all_yamls)


def main():
    parser = argparse.ArgumentParser(
        description='Generate VirtualMachine YAML manifests from scenarios'
    )
    parser.add_argument(
        '--scenario',
        type=str,
        default='mixed_load',
        help='Scenario name (default: mixed_load)'
    )
    parser.add_argument(
        '--output',
        type=str,
        help='Output file (default: stdout)'
    )
    parser.add_argument(
        '--list',
        action='store_true',
        help='List available scenarios'
    )

    args = parser.parse_args()

    if args.list:
        scenarios = ScenarioLoader.create_sample_scenarios()
        print("Available scenarios:")
        for name, nodes in scenarios.items():
            total_vms = sum(len(node.vms) for node in nodes)
            print(f"  - {name}: {len(nodes)} nodes, {total_vms} VMs")
        return 0

    yaml_content = generate_scenario_yaml(args.scenario)
    if yaml_content is None:
        return 1

    if args.output:
        with open(args.output, 'w') as f:
            f.write(yaml_content)
        print(f"Generated {args.output} from scenario '{args.scenario}'", file=sys.stderr)
    else:
        print(yaml_content)

    return 0


if __name__ == '__main__':
    sys.exit(main())
