# ADR 0003: Generation for E2A v1.1 is removed in v1.3.0

- **Status:** Accepted
- **Date:** v1.2.2 deprecation, v1.3.0 removal
- **Deciders:** repository owner

## Context

Maintaining two generations of output doubled the surface.

## Options considered

A) Keep both. B) Warn in v1.2.2, remove in v1.3.0.

## Decision

B.

## Consequences

A migration path was documented; v1.1 projects pin an older tag.
