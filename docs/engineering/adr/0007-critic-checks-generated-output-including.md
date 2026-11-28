# ADR 0007: A critic checks generated output (including syntax of generated Node code)

- **Status:** Accepted
- **Date:** v1.2.x, v1.6.0
- **Deciders:** repository owner

## Context

Generated code can be wrong in ways tests of A2C itself do not see.

## Options considered

A) Trust the generator. B) A critic agent reviews output; v1.6.0 syntax-checks generated Node output with `tsc`.

## Decision

B.

## Consequences

More defects are caught before the project's first commit; the critics need maintenance as outputs evolve.
