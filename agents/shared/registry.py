"""Service registry reader.

Parses ``registry/catalog-info.yaml`` and exposes query helpers that agents
use to resolve service ownership, dependency graphs, and contract paths.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ContractPaths:
    openapi: str | None
    event_schema: str | None
    db_schema: str | None


@dataclass
class DeploymentInfo:
    environment: str
    infrastructure: str
    deploy_dependencies: list[str] = field(default_factory=list)


@dataclass
class ServiceEntry:
    name: str
    repo: str
    owner: str
    language: str
    framework: str
    service_type: str
    depends_on: list[str]
    consumed_by: list[str]
    events_published: list[str]
    events_consumed: list[str]
    contract_paths: ContractPaths
    deployment: DeploymentInfo


class Registry:
    """Loads and queries the service catalog.

    Args:
        catalog_path: Path to ``catalog-info.yaml``. Defaults to the
                      standard location relative to the repository root.
    """

    def __init__(self, catalog_path: str | Path | None = None) -> None:
        if catalog_path is None:
            catalog_path = Path(__file__).parents[2] / "registry" / "catalog-info.yaml"
        self._path = Path(catalog_path)
        self._services: dict[str, ServiceEntry] = {}
        self._load()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        with self._path.open() as fh:
            raw: dict[str, Any] = yaml.safe_load(fh)
        for entry in raw.get("services", []):
            svc = self._parse_entry(entry)
            self._services[svc.name] = svc

    @staticmethod
    def _parse_entry(data: dict[str, Any]) -> ServiceEntry:
        cp = data.get("contract_paths") or {}
        dep = data.get("deployment") or {}
        return ServiceEntry(
            name=data["name"],
            repo=data["repo"],
            owner=data["owner"],
            language=data["language"],
            framework=data["framework"],
            service_type=data["service_type"],
            depends_on=data.get("depends_on") or [],
            consumed_by=data.get("consumed_by") or [],
            events_published=data.get("events_published") or [],
            events_consumed=data.get("events_consumed") or [],
            contract_paths=ContractPaths(
                openapi=cp.get("openapi"),
                event_schema=cp.get("event_schema"),
                db_schema=cp.get("db_schema"),
            ),
            deployment=DeploymentInfo(
                environment=dep.get("environment", ""),
                infrastructure=dep.get("infrastructure", ""),
                deploy_dependencies=dep.get("deploy_dependencies") or [],
            ),
        )

    # ------------------------------------------------------------------
    # Public query API
    # ------------------------------------------------------------------

    def all_services(self) -> list[ServiceEntry]:
        """Return all registered services."""
        return list(self._services.values())

    def get_service(self, name: str) -> ServiceEntry | None:
        """Return the service entry for *name*, or ``None`` if not found."""
        return self._services.get(name)

    def services_affected_by_event(self, event_type: str) -> list[ServiceEntry]:
        """Return services that publish *or* consume *event_type*."""
        return [svc for svc in self._services.values() if event_type in svc.events_published or event_type in svc.events_consumed]

    def downstream_services(self, service_name: str) -> list[ServiceEntry]:
        """Return services that directly depend on *service_name*."""
        return [svc for svc in self._services.values() if service_name in svc.depends_on]

    def upstream_services(self, service_name: str) -> list[ServiceEntry]:
        """Return services that *service_name* directly depends on."""
        svc = self.get_service(service_name)
        if svc is None:
            return []
        return [self._services[dep] for dep in svc.depends_on if dep in self._services]

    def build_context_summary(self, service_names: list[str]) -> str:
        """Return a human-readable summary of *service_names* and their relationships."""
        lines: list[str] = []
        for name in service_names:
            svc = self.get_service(name)
            if svc is None:
                continue
            lines.append(f"**{svc.name}** ({svc.service_type}, {svc.language}/{svc.framework})")
            lines.append(f"  Repo: {svc.repo}")
            lines.append(f"  Owner: {svc.owner}")
            if svc.depends_on:
                lines.append(f"  Depends on: {', '.join(svc.depends_on)}")
            if svc.consumed_by:
                lines.append(f"  Consumed by: {', '.join(svc.consumed_by)}")
            if svc.events_published:
                lines.append(f"  Publishes: {', '.join(svc.events_published)}")
            if svc.events_consumed:
                lines.append(f"  Consumes: {', '.join(svc.events_consumed)}")
            lines.append("")
        return "\n".join(lines)

    def find_services_by_keyword(self, keyword: str) -> list[ServiceEntry]:
        """Return services whose name, events, or framework mention *keyword*."""
        keyword_lower = keyword.lower()
        results = []
        for svc in self._services.values():
            fields = [
                svc.name,
                svc.framework,
                svc.language,
                " ".join(svc.events_published),
                " ".join(svc.events_consumed),
            ]
            if any(keyword_lower in f.lower() for f in fields):
                results.append(svc)
        return results


if __name__ == "__main__":
    import sys

    if "--validate" in sys.argv:
        from scripts.validate_registry import main as validate_main

        sys.exit(validate_main())
    else:
        print("Usage: python -m agents.shared.registry --validate")
        sys.exit(1)
