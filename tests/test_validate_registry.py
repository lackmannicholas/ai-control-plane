"""Tests for the registry validation script."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from scripts.validate_registry import validate


@pytest.fixture()
def valid_catalog(tmp_path: Path) -> Path:
    content = textwrap.dedent("""
        schema_version: "1.0"
        services:
          - name: svc-a
            repo: https://github.com/org/svc-a
            owner: "@org/team"
            language: Python
            framework: FastAPI
            service_type: api
            depends_on: []
            consumed_by: []
            events_published:
              - thing.happened
            events_consumed: []
            contract_paths:
              openapi: openapi/spec.yaml
              event_schema: null
              db_schema: null
            deployment:
              environment: production
              infrastructure: k8s
              deploy_dependencies: []
    """)
    path = tmp_path / "catalog-info.yaml"
    path.write_text(content)
    return path


class TestValidateRegistry:
    def test_valid_catalog_returns_no_errors(self, valid_catalog: Path):
        assert validate(valid_catalog) == []

    def test_missing_required_field_detected(self, tmp_path: Path):
        content = textwrap.dedent("""
            schema_version: "1.0"
            services:
              - name: bad-svc
                repo: https://github.com/org/bad-svc
                owner: "@org/team"
                language: Python
                # framework is missing
                service_type: api
                depends_on: []
                events_published: []
                events_consumed: []
                contract_paths: {}
                deployment: {}
        """)
        path = tmp_path / "catalog-info.yaml"
        path.write_text(content)
        errors = validate(path)
        assert any("framework" in e for e in errors)

    def test_invalid_service_type_detected(self, tmp_path: Path):
        content = textwrap.dedent("""
            schema_version: "1.0"
            services:
              - name: svc
                repo: https://github.com/org/svc
                owner: "@org/team"
                language: Python
                framework: FastAPI
                service_type: invalid-type
                depends_on: []
                events_published: []
                events_consumed: []
                contract_paths: {}
                deployment: {}
        """)
        path = tmp_path / "catalog-info.yaml"
        path.write_text(content)
        errors = validate(path)
        assert any("service_type" in e for e in errors)

    def test_unknown_dependency_detected(self, tmp_path: Path):
        content = textwrap.dedent("""
            schema_version: "1.0"
            services:
              - name: svc
                repo: https://github.com/org/svc
                owner: "@org/team"
                language: Python
                framework: FastAPI
                service_type: api
                depends_on:
                  - ghost-service
                events_published: []
                events_consumed: []
                contract_paths: {}
                deployment: {}
        """)
        path = tmp_path / "catalog-info.yaml"
        path.write_text(content)
        errors = validate(path)
        assert any("ghost-service" in e for e in errors)

    def test_unconsumed_event_detected(self, tmp_path: Path):
        content = textwrap.dedent("""
            schema_version: "1.0"
            services:
              - name: svc
                repo: https://github.com/org/svc
                owner: "@org/team"
                language: Python
                framework: FastAPI
                service_type: api
                depends_on: []
                events_published: []
                events_consumed:
                  - orphan.event
                contract_paths: {}
                deployment: {}
        """)
        path = tmp_path / "catalog-info.yaml"
        path.write_text(content)
        errors = validate(path)
        assert any("orphan.event" in e for e in errors)
