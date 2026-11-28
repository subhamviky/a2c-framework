# Engineering records: a2c-framework

The Architecture-to-Code platform: A2C (agents that generate code, IaC and pipelines), G2C and P0 (starters), built on E2A.

| Area | Document |
|---|---|
| Decisions | [ADRs](adr/README.md) |
| Security | [Threat model](security/threat-model.md), [data handling](security/data-handling.md) |
| Delivery | [Release process](operations/release-process.md), [`CHANGELOG.md`](../../CHANGELOG.md) |
| Support | [Support and vulnerability handling](operations/support-and-vulnerabilities.md) |
| Quality | [Test strategy](testing/test-strategy.md) |
| Product | [Requirements and user stories](product/requirements-and-user-stories.md), [solution overview](product/solution-overview.md), [onboarding](product/onboarding.md) |

**Not applicable to a library, and why.** SLOs and an error budget, incident response, disaster recovery, cost and capacity, teardown and an HTTP API reference describe a *running service*. a2c-framework is code that other projects install and pin to a tag: it has no deployment, no traffic and no data of its own. Their service-level equivalents are in the [assistant repository](https://github.com/subhamviky/enterprise-finance-genai-assistant/blob/main/docs/engineering/README.md) and the other service repositories. The library's public interface is documented in its design documents and its code (listed in the onboarding page).

Related: [E2A](https://github.com/subhamviky/e2a-framework) (what it generates for) and the projects scaffolded with it.

> **Status:** all documents here are drafts written on 28 November 2026 from the repository history, design documents, drills and tests, awaiting the owner's review. Where a date or a detail was not recorded, the document says so.
