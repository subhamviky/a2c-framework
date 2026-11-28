# Release process: a2c-framework

1. **Branch and pull request.** CI (`ci`): checks out E2A as the single source of its classes; packaging check of the *installed* package; installs e2a-java for the Java smoke test; the TypeScript compiler for generated Node output; E2A conformance (strict); the smoke tests; generation of a service, build of its image and a probe of the running container.
2. **Merge to `main`.**
3. **Tag `vX.Y.Z`.** Generated projects record the A2C version in their provenance; `--upgrade` uses it. A tag is never moved.
4. **CHANGELOG entry** per version, naming the E2A version it was verified against and what the first live run found (v1.5.4 and v1.6.1 and v1.6.2 were all fixes found by consuming projects).
5. **Rollback.** Projects repin the previous tag; generated output is in their repository and is reverted with git.

Compatibility: additive by default; v1.1 generation was deprecated in v1.2.2 and removed in v1.3.0.
