# ADR 0001: Generate at generation time: the request file declares everything

- **Status:** Accepted
- **Date:** v1.2.0
- **Deciders:** repository owner

## Context

Architectural discipline (NFRs, IaC, CI/CD, security) was applied after the code, if at all.

## Options considered

A) Review after generation. B) A request file declares the service, its settings, contracts, Maven or Poetry coordinates and monorepo layout; A2C generates code, IaC and pipelines that satisfy the declaration.

## Decision

B (`a2c_contracts`, `a2c_settings`, `a2c_layout`).

## Consequences

Projects start inside the guardrails. A declaration must be complete; an under-declared service fails generation rather than guessing.
