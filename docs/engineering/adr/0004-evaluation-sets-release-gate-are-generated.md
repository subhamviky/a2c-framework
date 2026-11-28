# ADR 0004: Evaluation sets and the release gate are generated into services

- **Status:** Accepted
- **Date:** v1.2.1, v1.6.0
- **Deciders:** repository owner

## Context

Generated services had tests but no evaluation or gate.

## Options considered

A) Leave to the project. B) Generate `evals/` and a release-gate step using E2A's `ProjectReleaseGate`; v1.6.0 adds evaluation in generated services and stronger critics.

## Decision

B (the generated gate step was fixed to valid YAML in v1.6.1).

## Consequences

Every generated service starts with a gate. Generated YAML must itself be validated (v1.6.1).
