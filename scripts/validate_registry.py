"""Registry validation script.

Validates ``registry/catalog-info.yaml`` for:
1. Schema completeness — all required fields are present per service entry.
2. Dependency graph consistency — every entry in ``depends_on`` references a
   known service name.
3. Event consistency — every ``events_consumed`` entry is published by at least
   one registered service.

Exit code 0 = valid.  Non-zero = validation errors found.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REQUIRED_FIELDS = {
    "name",
    "repo",
    "owner",
    "language",
    "framework",
    "service_type",
}

VALID_SERVICE_TYPES = {"api", "worker", "frontend", "library", "infrastructure"}


def validate(catalog_path: Path) -> list[str]:
    """Return a list of validation error messages (empty = valid)."""
    with catalog_path.open() as fh:
        raw = yaml.safe_load(fh)

    errors: list[str] = []
    services = raw.get("services", [])

    if not isinstance(services, list):
        return ["'services' key must be a list."]

    names: set[str] = {s.get("name") for s in services if s.get("name")}
    all_published: set[str] = set()
    for svc in services:
        all_published.update(svc.get("events_published") or [])

    for svc in services:
        name = svc.get("name", "<unnamed>")

        # Required fields
        for field in REQUIRED_FIELDS:
            if not svc.get(field):
                errors.append(f"[{name}] Missing required field: {field}")

        # service_type enum
        stype = svc.get("service_type")
        if stype and stype not in VALID_SERVICE_TYPES:
            errors.append(
                f"[{name}] Invalid service_type '{stype}'. "
                f"Must be one of: {sorted(VALID_SERVICE_TYPES)}"
            )

        # Dependency graph consistency
        for dep in svc.get("depends_on") or []:
            if dep not in names:
                errors.append(f"[{name}] depends_on references unknown service: '{dep}'")

        # Event consistency
        for event in svc.get("events_consumed") or []:
            if event not in all_published:
                errors.append(
                    f"[{name}] consumes event '{event}' which is not published "
                    f"by any registered service."
                )

    return errors


def main() -> int:
    catalog_path = Path(__file__).parents[1] / "registry" / "catalog-info.yaml"
    if not catalog_path.exists():
        print(f"ERROR: catalog-info.yaml not found at {catalog_path}", file=sys.stderr)
        return 1

    errors = validate(catalog_path)
    if errors:
        print("Registry validation FAILED:\n", file=sys.stderr)
        for err in errors:
            print(f"  • {err}", file=sys.stderr)
        return 1

    print(f"Registry validation PASSED ({catalog_path})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
