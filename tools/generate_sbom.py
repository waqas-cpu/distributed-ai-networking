#!/usr/bin/env python3
"""Generate CycloneDX or SPDX Software Bill of Materials (SBOM) for the platform."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from typing import Any, Dict, List


def calculate_sha256(filepath: str) -> str:
    """Calculate SHA-256 digest of a local file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def parse_requirements(requirements_path: str = "requirements.txt") -> List[Dict[str, str]]:
    """Parse pinned dependencies from requirements.txt."""
    dependencies = []
    if not os.path.exists(requirements_path):
        return dependencies

    with open(requirements_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "==" in line:
                name, version = line.split("==", 1)
                dependencies.append({"name": name.strip(), "version": version.strip()})
            elif ">=" in line:
                name, version = line.split(">=", 1)
                dependencies.append({"name": name.strip(), "version": f">={version.strip()}"})
            else:
                dependencies.append({"name": line.strip(), "version": "unknown"})
    return dependencies


def generate_cyclonedx_sbom(
    dependencies: List[Dict[str, str]],
    project_name: str = "distributed-ai-networking",
    version: str = "1.0.0",
) -> Dict[str, Any]:
    """Generate a CycloneDX 1.5 compliant SBOM JSON document."""
    components = []

    # Add core system components
    core_modules = [
        ("gateway", "gateway/app.py"),
        ("decision_engine", "decision_engine/engine.py"),
        ("scheduler", "scheduler/dispatcher.py"),
        ("node_agent", "node_agent/worker.py"),
        ("results_aggregator", "results_aggregator/aggregator.py"),
        ("telemetry", "telemetry/store.py"),
        ("common", "common/supply_chain.py"),
    ]

    for mod_name, file_rel in core_modules:
        comp: Dict[str, Any] = {
            "type": "application",
            "name": f"{project_name}/{mod_name}",
            "version": version,
            "description": f"Internal microservice/module: {mod_name}",
        }
        if os.path.exists(file_rel):
            comp["hashes"] = [{"alg": "SHA-256", "content": calculate_sha256(file_rel)}]
        components.append(comp)

    # Add third-party library dependencies
    for dep in dependencies:
        comp = {
            "type": "library",
            "name": dep["name"],
            "version": dep["version"],
            "purl": f"pkg:pypi/{dep['name']}@{dep['version']}",
            "scope": "required",
        }
        components.append(comp)

    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{hashlib.md5(str(time.time()).encode()).hexdigest()}",
        "version": 1,
        "metadata": {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "tools": [{"vendor": "DistributedAI", "name": "sbom-generator", "version": "1.0.0"}],
            "component": {
                "type": "application",
                "name": project_name,
                "version": version,
                "description": "Distributed AI Workload Orchestration Platform",
            },
        },
        "components": components,
    }
    return sbom


def generate_spdx_sbom(
    dependencies: List[Dict[str, str]],
    project_name: str = "distributed-ai-networking",
    version: str = "1.0.0",
) -> Dict[str, Any]:
    """Generate an SPDX 2.3 compliant SBOM JSON document."""
    packages = []
    
    # Root package
    packages.append({
        "SPDXID": "SPDXRef-RootPackage",
        "name": project_name,
        "versionInfo": version,
        "downloadLocation": "https://github.com/distributed-ai/orchestration",
        "packageSupplier": "Organization: Distributed AI Security Team",
    })

    for i, dep in enumerate(dependencies, 1):
        packages.append({
            "SPDXID": f"SPDXRef-Package-{i}",
            "name": dep["name"],
            "versionInfo": dep["version"],
            "downloadLocation": "NOASSERTION",
            "externalRefs": [
                {
                    "referenceCategory": "PACKAGE-MANAGER",
                    "referenceType": "purl",
                    "referenceLocator": f"pkg:pypi/{dep['name']}@{dep['version']}",
                }
            ],
        })

    spdx = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"{project_name}-SBOM",
        "documentNamespace": f"https://spdx.org/spdxdocs/{project_name}-{version}-{int(time.time())}",
        "creationInfo": {
            "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "creators": ["Tool: DistributedAI-SBOMGenerator-1.0"],
        },
        "packages": packages,
    }
    return spdx


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate SBOM for Distributed AI Orchestration Platform")
    parser.add_argument("--format", choices=["cyclonedx", "spdx"], default="cyclonedx", help="SBOM standard format")
    parser.add_argument("--requirements", default="requirements.txt", help="Path to requirements.txt")
    parser.add_argument("--output", default="sbom.json", help="Output file path")
    args = parser.parse_args()

    deps = parse_requirements(args.requirements)
    if args.format == "cyclonedx":
        sbom_data = generate_cyclonedx_sbom(deps)
    else:
        sbom_data = generate_spdx_sbom(deps)

    content = json.dumps(sbom_data, indent=2)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(content + "\n")

    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    print(f"Generated {args.format.upper()} SBOM -> {args.output}")
    print(f"SBOM SHA-256: sha256:{digest}")
    print(f"Total Components/Packages: {len(sbom_data.get('components', sbom_data.get('packages', [])))}")


if __name__ == "__main__":
    main()
