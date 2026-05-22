# A2C: Architecture-to-Code Developer Platform Framework

An AI-governed software factory framework designed to programmatically enforce enterprise-grade architectural discipline, Infrastructure-as-Code (IaC), and secure CI/CD pipelines at generation time.

**Built on top of the [E2A Architecture Framework](https://github.com/subhamviky/e2a-framework)**

---

## 💡 The Meta-Insight: Self-Referential Governance

The E2A Framework has a natural extension in A2C. E2A governs how agentic AI applications are built. A2C applies E2A's own structural governance mechanisms (`BaseAgent.run()` with strict idempotency loops, latency SLO boundaries, policy enforcement, and automated quality evaluation gates) to **generate code that itself complies with E2A standards**. 

The generator agent is governed by E2A. The output artifact is governed by E2A. Architecture is enforced structurally at generation time — not discovered later through costly production failures.

| Dimension | E2A Framework | A2C Framework |
| :--- | :--- | :--- |
| **Core Target** | Governs runtime agentic AI applications. | Generates governed enterprise software assets. |
| **Input Interface** | `AgentState` (query, intent, history). | `DevRequest` (project_name, mandatory_nfrs, target_cloud). |
| **Output Artifact** | Validated agent responses, context-grounded RAG answers. | Production-grade microservice code, Terraform IaC, CI/CD pipelines. |

---

## The Five Failure Modes A2C Fixes

| Failure Mode | What happens without A2C | A2C solution |
|---|---|---|
| **NFR Amnesia** | Generated code has no idempotency, no circuit breakers | `_apply_policy()` injects 6 mandatory NFRs before any LLM call |
| **Architecture Drift** | Business logic lands in route handlers, no service layers | `_build_messages()` encodes Clean Architecture as a hard requirement |
| **Governance Gap** | No policy-as-code, no approval gates in generated code | CodeCriticAgent validates NFR completeness score >= 0.75 |
| **IaC Afterthought** | Infrastructure manually configured, not version-controlled | IaCAgent generates Terraform as Phase 2 of the SDLC workflow |
| **CI/CD Bolted On** | No RAGAS gate, no vulnerability scan, no auto-rollback | CICDAgent generates GitHub Actions with OIDC, Trivy, RAGAS gate |

## Multi-Agent SDLC Workflow

DevRequest (input)
→ RequirementsAgent  — validates project_type, mandatory_nfrs, target_cloud
→ CodeGenAgent       — generates Clean Architecture microservice code
→ IaCAgent           — generates Terraform (AWS / GCP / Azure)
→ CICDAgent          — generates GitHub Actions with OIDC, RAGAS gate, Trivy, rollback
→ CodeCriticAgent    — validates NFR completeness score >= 0.75
→ DeliveryState (output) — full project structure + validation report

## Built on E2A

A2C is a meta-application of the [E2A Architecture Framework](https://github.com/subhamviky/e2a-framework).
The same abstract class hierarchy that governs agentic AI systems is used here
to build the developer platform that generates those systems.
The agent is governed by E2A. The generated code follows E2A.
Architecture is enforced as a structural constraint, not a prompt suggestion.

---
**Author:** Subham Gupta — Staff Architect
[![LinkedIn](https://img.shields.io/badge/LinkedIn-Connect-0077B5?logo=linkedin)](https://linkedin.com/in/subham-gupta-0a05a058)
[![Email](https://img.shields.io/badge/Email-subhamviky@gmail.com-D14836?logo=gmail)](mailto:subhamviky@gmail.com)
