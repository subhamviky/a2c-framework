# Threat model: a2c-framework

- **Status:** Draft 2026-11-28, awaiting owner review · STRIDE for a code generator: the risks are in what it writes into other people's projects and pipelines.

| # | Threat | Control | Evidence |
|---|---|---|---|
| A1 | **Tampering**: generated code bypasses the safety order | generated services subclass E2A with conformance in their CI (strict) | `a2c_*` generators |
| A2 | **Tampering**: a generated pipeline is invalid or insecure | a critic reviews output; YAML validity is tested (v1.6.1); the image scanner is resolved by the workflow (v1.6.2); the release-gate step is generated | CHANGELOG |
| A3 | **Spoofing/repudiation**: who generated or changed what | provenance recorded for every run; workflow commits signed as GitHub signs them (v1.5.4) | `a2c_provenance`, `a2c_signed_push` |
| A4 | **Information disclosure**: secrets in generated output | generated services read secrets from a secret store; no key is written into code | settings contract |
| A5 | **Elevation**: the cloud account used by generation workflows | workflows use the project's cloud identity (`aidlc-change` through the cloud account, v1.5.2), not a stored key | `aidlc-*.yml` |
| A6 | **Supply chain**: generated projects pin E2A and base images | tags are pinned in generated manifests; the vulnerability scan is part of the generated pipeline | generated delivery workflow |

Residual: dependency and supply-chain risk is managed by pinning tags and running CI, not by signing or an SBOM policy; a consuming project must run the conformance kit to benefit from the safety order; there is no penetration test.
