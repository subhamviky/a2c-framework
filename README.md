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

## 🛠️ The Architecture Factory Workflow

Traditional LLM code generators produce functional standalone code snippets but fail to maintain structural Non-Functional Requirements (NFRs), resulting in a critical operational risk known as **"NFR Amnesia."** A2C addresses this failure vector systematically by executing a structured multi-agent SDLC workflow pipeline:
