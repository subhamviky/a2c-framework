# Onboarding

Read: `README.md`, the design documents under `docs/`, then the [ADRs](../adr/README.md).

Run locally: install the package, check out E2A beside it (A2C takes E2A's classes from there), run the smoke tests and the generation probe as in `.github/workflows/ci.yml`.

Map: the `a2c_*` modules (generators, contracts, settings, layout, provenance, change, upgrade, signed push), `g2c_*` (service generation), `base_*` and generator agents, `examples/`, `docs/`. Working agreements: one concern per branch; CI green; verify a new generator in a real consuming project and record what it found in the CHANGELOG.
