"""Tests for the service registry."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from agents.shared.registry import Registry


@pytest.fixture()
def catalog_yaml(tmp_path: Path) -> Path:
    content = textwrap.dedent("""
        schema_version: "1.0"
        services:
          - name: svc-a
            repo: https://github.com/org/svc-a
            owner: "@org/team-a"
            language: Python
            framework: FastAPI
            service_type: api
            depends_on: []
            consumed_by:
              - svc-b
            events_published:
              - order.created
            events_consumed: []
            contract_paths:
              openapi: openapi/svc-a.yaml
              event_schema: schemas/events/
              db_schema: db/models/
            deployment:
              environment: production
              infrastructure: kubernetes
              deploy_dependencies: []

          - name: svc-b
            repo: https://github.com/org/svc-b
            owner: "@org/team-b"
            language: TypeScript
            framework: Node.js
            service_type: worker
            depends_on:
              - svc-a
            consumed_by: []
            events_published: []
            events_consumed:
              - order.created
            contract_paths:
              openapi: null
              event_schema: schemas/events/
              db_schema: null
            deployment:
              environment: production
              infrastructure: kubernetes
              deploy_dependencies: []
    """)
    path = tmp_path / "catalog-info.yaml"
    path.write_text(content)
    return path


class TestRegistryLoad:
    def test_loads_all_services(self, catalog_yaml: Path):
        reg = Registry(catalog_yaml)
        services = reg.all_services()
        assert len(services) == 2

    def test_service_fields_parsed_correctly(self, catalog_yaml: Path):
        reg = Registry(catalog_yaml)
        svc = reg.get_service("svc-a")
        assert svc is not None
        assert svc.name == "svc-a"
        assert svc.language == "Python"
        assert svc.service_type == "api"
        assert svc.events_published == ["order.created"]

    def test_get_nonexistent_service_returns_none(self, catalog_yaml: Path):
        reg = Registry(catalog_yaml)
        assert reg.get_service("does-not-exist") is None

    def test_upstream_services(self, catalog_yaml: Path):
        reg = Registry(catalog_yaml)
        upstream = reg.upstream_services("svc-b")
        assert len(upstream) == 1
        assert upstream[0].name == "svc-a"

    def test_downstream_services(self, catalog_yaml: Path):
        reg = Registry(catalog_yaml)
        downstream = reg.downstream_services("svc-a")
        assert len(downstream) == 1
        assert downstream[0].name == "svc-b"

    def test_services_affected_by_event(self, catalog_yaml: Path):
        reg = Registry(catalog_yaml)
        affected = reg.services_affected_by_event("order.created")
        names = {svc.name for svc in affected}
        assert names == {"svc-a", "svc-b"}

    def test_find_services_by_keyword(self, catalog_yaml: Path):
        reg = Registry(catalog_yaml)
        results = reg.find_services_by_keyword("fastapi")
        assert len(results) == 1
        assert results[0].name == "svc-a"

    def test_build_context_summary_contains_service_names(self, catalog_yaml: Path):
        reg = Registry(catalog_yaml)
        summary = reg.build_context_summary(["svc-a", "svc-b"])
        assert "svc-a" in summary
        assert "svc-b" in summary

    def test_upstream_of_unknown_service_returns_empty(self, catalog_yaml: Path):
        reg = Registry(catalog_yaml)
        assert reg.upstream_services("ghost-service") == []
