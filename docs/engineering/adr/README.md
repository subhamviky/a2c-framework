# Architecture Decision Records

One record per significant decision (context, options, decision, consequences). Records are not edited to change history: a reversed decision gets a new record that supersedes the old one. These are the decisions of the A2C, G2C and P0 generation framework. Platform-wide decisions (free tier, synthetic data, Workload Identity Federation, promotion, the documentation layout) are in the [assistant repository's ADR index](https://github.com/subhamviky/enterprise-finance-genai-assistant/blob/main/docs/engineering/adr/README.md).

Template: [`0000-template.md`](0000-template.md).

| # | Decision | Status |
|---|---|---|
| [0001](0001-generate-at-generation-time-request-file.md) | Generate at generation time: the request file declares everything | Accepted |
| [0002](0002-a2c-generates-for-e2a-takes-e2a-classes-from.md) | A2C generates for E2A and takes E2A's classes from one source | Accepted |
| [0003](0003-generation-for-e2a-v1-1-is-removed-v1-3-0.md) | Generation for E2A v1.1 is removed in v1.3.0 | Accepted |
| [0004](0004-evaluation-sets-release-gate-are-generated.md) | Evaluation sets and the release gate are generated into services | Accepted |
| [0005](0005-developer-trail-for-every-run-aidlc-change.md) | A developer's trail for every run, and `aidlc-change` to change existing code | Accepted |
| [0006](0006-generated-services-bind-their-model-from.md) | Generated services bind their model from a profile | Accepted |
| [0007](0007-critic-checks-generated-output-including.md) | A critic checks generated output (including syntax of generated Node code) | Accepted |
| [0008](0008-generated-delivery-workflows-resolve-their-own.md) | Generated delivery workflows resolve their own image scanner | Accepted |
