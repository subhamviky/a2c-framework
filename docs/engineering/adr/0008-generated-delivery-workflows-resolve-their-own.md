# ADR 0008: Generated delivery workflows resolve their own image scanner

- **Status:** Accepted
- **Date:** v1.6.2
- **Deciders:** repository owner

## Context

The generated workflow's image scan step could not find its scanner (found by consuming projects).

## Options considered

A) Document. B) Generate a step that resolves the scanner it uses.

## Decision

B.

## Consequences

The scan step works out of the box; the vulnerability scan in the assistant's pipeline comes from this template.
