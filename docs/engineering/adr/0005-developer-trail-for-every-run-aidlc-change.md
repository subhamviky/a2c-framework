# ADR 0005: A developer's trail for every run, and `aidlc-change` to change existing code

- **Status:** Accepted
- **Date:** v1.5.0
- **Deciders:** repository owner

## Context

Generation covered new projects only, and there was no record of what was generated or by whom.

## Options considered

A) Regenerate over existing code. B) Provenance (`a2c_provenance`) recorded for each run; `aidlc-change` applies a change to existing Python (v1.5.0), Java (v1.5.1) and through the cloud account (v1.5.2).

## Decision

B, with `--upgrade` using provenance.

## Consequences

Existing projects can be changed with a trail. Workflow commits had to be tuned to what GitHub really signs (v1.5.4).
