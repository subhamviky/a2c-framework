# ADR 0006: Generated services bind their model from a profile

- **Status:** Accepted
- **Date:** v1.4.0
- **Deciders:** repository owner

## Context

Model choice was hard-coded in generated code.

## Options considered

A) Fixed model. B) A profile selects the provider and features (`e2a-managed-providers`), configured by environment.

## Decision

B (P27).

## Consequences

A free-tier model, a frontier model or the simulated model is a configuration change.
