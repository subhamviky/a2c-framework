# ADR 0002: A2C generates for E2A and takes E2A's classes from one source

- **Status:** Accepted
- **Date:** v1.2.0
- **Deciders:** repository owner

## Context

Generated services must use the same safety order as hand-written ones.

## Options considered

A) Copy E2A's classes into generated code. B) Generated services depend on E2A (Python) and e2a-java (Java); A2C's CI checks out E2A as the single source.

## Decision

B.

## Consequences

A fix in E2A reaches generated services by upgrade. A2C and E2A versions must be compatible (stated in the CHANGELOG).
