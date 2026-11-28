# Requirements and user stories

| # | As a... | I want... | So that... | Acceptance |
|---|---|---|---|---|
| A1 | architect | to declare a service in one request file | the code, IaC and pipeline match the declaration | `aidlc-build` generates from the request |
| A2 | developer | generated services to start with NFRs, tests, a gate and a vulnerability scan | I begin inside the guardrails | generated pipeline and `evals/` |
| A3 | developer | to change existing code with the same discipline | I am not forced to regenerate | `aidlc-change` for Python and Java |
| A4 | tech lead | a trail of what was generated or changed | I can audit it | provenance per run |
| A5 | developer | the model to be a configuration | I can use any supported model | profile-bound services |
| A6 | maintainer | upgrades of generated projects | they follow the frameworks | `--upgrade` with provenance |

Out of scope: running the generated service, hosting, a UI.
