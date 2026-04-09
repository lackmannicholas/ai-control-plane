# Workflows

This directory documents the GitHub Actions workflows that power the AI control plane.
The actual workflow YAML files are stored in `.github/workflows/` as required by GitHub Actions.

## Workflow Inventory

| File | Trigger | Purpose |
|------|---------|---------|
| [prd-refiner.yml](../.github/workflows/prd-refiner.yml) | `issues: labeled` (epic), `issue_comment` (refining issues) | Runs the PRD Refiner Agent to iterate with the PM and produce a structured specification |
| [architect.yml](../.github/workflows/architect.yml) | `issues: labeled` (architect-ready, approved-for-dispatch), `issue_comment` (architect-planning issues) | Runs the Architect Agent to produce and dispatch the execution plan |
| [registry-sync.yml](../.github/workflows/registry-sync.yml) | `push`/`pull_request` touching `registry/**` | Validates catalog-info.yaml and checks dependency graph consistency |
| [ci.yml](../.github/workflows/ci.yml) | `push`/`pull_request` | Runs unit tests and linter checks |

## Label State Machine

```
[epic]  →  [refining]  →  [spec-ready]  →  [architect-ready]
                                ↓
                        [architect-planning]
                                ↓
                        [approved-for-dispatch]
                                ↓
                          [dispatching]  →  [in-progress]
```

## Required Repository Secrets

| Secret | Used By | Description |
|--------|---------|-------------|
| `ANTHROPIC_API_KEY` | prd-refiner, architect | Anthropic Claude API key for LLM inference |
| `GITHUB_TOKEN` | All workflows | Automatically injected by GitHub Actions |

## Adding a New Spoke Repository

1. Write `system-context.md` in the spoke repo describing the service.
2. Add the service entry to `registry/catalog-info.yaml` in this repo.
3. Add the contract sync GitHub Action to the spoke repo (see onboarding template).
4. Open a PR to the hub — the registry sync validator will verify the entry.
