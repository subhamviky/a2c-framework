# A2C: Architecture-to-Code Developer Platform Framework

> **An AI-governed software factory framework designed to programmatically enforce enterprise-grade architectural discipline, Infrastructure-as-Code (IaC), and secure CI/CD pipelines at generation time.**

[![Status: Active Design](https://img.shields.io/badge/Status-Active%20Design-yellow.svg)](https://github.com/subhamviky/a2c-framework)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python: 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![Built on: E2A Architecture Framework](https://img.shields.io/badge/Built%20on-E2A%20Framework-purple.svg)](https://github.com/subhamviky/e2a-framework)
[![Article: Context, Harness & Evals](https://img.shields.io/badge/Architecture%20Paper-Context%2C%20Harness%20%26%20Evals-0A66C2.svg)](https://www.linkedin.com/pulse/context-harness-evals-what-ai-assisted-sdlc-can-borrow-subham-gupta-fplfc/)

---

## 🏛️️ Executive Summary: The AI-Assisted SDLC as a Cloud-Native Pipeline

Modern autonomous developer tooling (Claude Code, GitHub Copilot, Gemini Code Assist) accelerates coding velocity. However, without deterministic structural guardrails, generated code frequently suffers from architectural drift, omitted non-functional requirements (NFRs), and unverified deployment scripts.

A2C operationalizes the core architectural thesis established in [Context, Harness, and Evals: What the AI-Assisted SDLC Can Borrow from Distributed Systems](https://www.linkedin.com/pulse/context-harness-evals-what-ai-assisted-sdlc-can-borrow-subham-gupta-fplfc/):

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   THE A2C GENERATION PIPELINE                                   │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
                                                 │
                                                 ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│ 1. CONTEXT COMPILATION (G2C & P0)                                                               │
│    • G2C: Compiles declarative OpenAPI/OData specifications into type-safe Pydantic contracts   │
│    • P0: Analyzes repository ASTs to project bounded, tenant-scoped workspace manifests         │
└────────────────────────────────┬────────────────────────────────────────────────────────────────┘
                                 │ Bounded, Typed Read-Model Context
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│ 2. HARNESS-GOVERNED GENERATION (A2C Core & E2A BaseAgent)                                       │
│    • Single public orchestrator entry point enforcing policy gates before model execution       │
│    • Multi-agent generation: CodeGenAgent, IaCAgent (Terraform), and CICDAgent (GitHub Actions) │
│    • Ephemeral execution container sandboxes with scoped, non-amplifiable credentials           │
└────────────────────────────────┬────────────────────────────────────────────────────────────────┘
                                 │ Proposed Code & IaC Artifacts
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│ 3. LAYERED VERIFICATION GATES (A2C CodeCriticAgent)                                             │
│    • Deterministic AST linting: Asserts Clean Architecture boundaries and required interfaces   │
│    • Factual groundedness: Evaluates RAGAS Faithfulness (score >= 0.85) against domain specs    │
│    • Static analysis: Programmatic secret scanning and SAST checks before Git packaging         │
└────────────────────────────────┬────────────────────────────────────────────────────────────────┘
                                 │
                ┌────────────────┴────────────────┐
           Pass │                                 │ Fail
                ▼                                 ▼
┌─────────────────────────────────────────────────┐ ┌─────────────────────────────────────────────┐
│ 4. DETERMINISTIC COMMIT & PR                    │ │ 5. SAGA COMPENSATING ROLLBACK               │
│    • Commits verified codebase & Terraform IaC  │ │    • Cleanly rolls back ephemeral branch    │
│    • Registers deployment pipeline & telemetry  │ │    • Preserves valid base scaffolding (P0)  │
│    • Verified audit trail to local outbox       │ │    • Routes failure context to DLQ for SRE  │
└─────────────────────────────────────────────────┘ └─────────────────────────────────────────────┘
```

---

## 🎯 Multi-Stakeholder Value Realization

| Stakeholder Lens | Enterprise Risk Solved | How A2C Delivers Business Value |
| :--- | :--- | :--- |
| **Chief Architect & VP of Eng** | Architectural entropy & framework sprawl | **Clean Architecture by Construction:** Generated services automatically inherit strict interface contracts, ports, and adapters without developer shortcuts. |
| **CISO & Enterprise Risk** | Ungoverned AI code generation & secret leakage | **Deterministic Pre-Commit Gates:** AST static checks and SAST linters block commits containing hardcoded secrets, misconfigured permissions, or unvetted dependencies. |
| **FinOps & Cloud Economics** | Context window bloat & runaway generation costs | **AST Context Pruning (`P0`):** Strips syntactic noise and compiles minimal dependency closures (`scaffold-config.json`), optimizing LLM token budgets. |
| **SRE & Platform Operations** | Broken deployments & orphaned build artifacts | **Saga Compensation Pattern:** Automatically rolls back ephemeral branches and purges transient files upon downstream failure while preserving base scaffolding. |
| **Product Leadership** | Slow sprint velocity due to manual scaffolding | **Zero-Day Production Readiness:** Accelerates greenfield and modernization delivery cycles from weeks to minutes, generating production-grade services on day zero. |

---

## 💡 The Meta-Insight: Self-Referential Governance

The E2A Framework has a natural extension in A2C. E2A governs how runtime agentic AI applications execute safely. A2C applies E2A's own structural governance mechanisms (`BaseAgent.run()` with strict idempotency loops, latency SLO boundaries, policy enforcement, and automated quality evaluation gates) to **generate code that itself complies with E2A standards**.

The generator agent is governed by E2A. The output artifact is governed by E2A. Architecture is enforced structurally at generation time — not discovered later through costly production failures.

| Dimension | E2A Framework | A2C Framework |
| :--- | :--- | :--- |
| **Core Target** | Governs runtime agentic AI applications. | Generates governed enterprise software assets. |
| **Input Interface** | `AgentState` (query, intent, history). | `DevRequest` (project_name, mandatory_nfrs, target_cloud). |
| **Output Artifact** | Validated agent responses, context-grounded RAG answers. | Production-grade microservice code, Terraform IaC, CI/CD pipelines. |

---

## 🛡️ The Five Failure Modes A2C Fixes

| Failure Mode | What Happens Without A2C | A2C Cloud-Native Solution |
| :--- | :--- | :--- |
| **NFR Amnesia** | Generated code lacks idempotency keys, circuit breakers, and telemetry. | `_apply_policy()` injects 6 mandatory enterprise NFRs before any LLM generation call. |
| **Architecture Drift** | Business logic lands haphazardly inside HTTP route handlers; no clean service tiers. | `_build_messages()` encodes Clean Architecture (Ports & Adapters) as an immutable contract. |
| **Governance Gap** | No policy-as-code or quality evaluation gates in generated code. | `CodeCriticAgent` asserts pre-commit validation gates (NFR completeness $\ge 0.75$, RAGAS $\ge 0.85$). |
| **IaC Afterthought** | Infrastructure is manually provisioned, untracked, and prone to configuration drift. | `IaCAgent` generates modular production Terraform (AWS / GCP / Azure landing zones) as Phase 2 of the SDLC. |
| **CI/CD Bolted On** | Deployment lacks vulnerability scanning, automated rollback, or signed attestations. | `CICDAgent` synthesizes complete GitHub Actions pipelines with OIDC, Trivy, and automated rollback. |

---

## 🔄 Multi-Agent SDLC Workflow

```
[ DevRequest ] (input: project_type, mandatory_nfrs, target_cloud)
      │
      ▼
RequirementsAgent   ──▶ Validates project_type, schema parameters, target cloud landing zone
      │
      ▼
CodeGenAgent        ──▶ Generates Clean Architecture microservice code & domain models
      │
      ▼
IaCAgent            ──▶ Generates modular Terraform (VPC, private subnets, ECS/Cloud Run/ACA)
      │
      ▼
CICDAgent           ──▶ Generates GitHub Actions with OIDC, Trivy, RAGAS gate, and auto-rollback
      │
      ▼
CodeCriticAgent     ──▶ Deterministically validates AST structure & NFR completeness score >= 0.75
      │
      ▼
[ DeliveryState ]   ──▶ (output: full project directory tree + automated audit report)
```

*(Full multi-agent SDLC pipeline — `CodeGenAgent` → `CodeCriticAgent` → `IaCAgent` → `CICDAgent` — documented in detail as implementation progresses. This framework is currently in active design; P0 and G2C modules are specified and maintained within this repository family.)*

---

## 🧱 Built on E2A

A2C is a meta-application of the [E2A Architecture Framework](https://github.com/subhamviky/e2a-framework). The same abstract class hierarchy that governs agentic AI systems is used here to build the developer platform that generates those systems.

* **The agent is governed by E2A:** Inherits single entry point execution, non-amplifiable credentials, and token budgets.
* **The generated code follows E2A:** Outputs Clean Architecture microservices with mandatory operational NFRs.
* **Architecture is enforced structurally:** Applied as a compiler constraint, not a prompt suggestion.

---

## ⚡ P0 Extension — Project Bootstrap Framework

`P0` extends A2C with **Phase Zero scaffolding**: generating everything an enterprise project requires *before* A2C generates domain business logic.

**Why a separate class (not an extension):** `bootstrap()` runs once per project at creation. `SDLCAssistantAgent.run()` runs whenever a new component is generated. Merging them would force re-scaffolding on every code generation call. The correct design: two independent classes composed via `BootstrapAndGenerateWorkflow`.

```python
# Option 1 — Bootstrap only
bootstrapper = ProjectBootstrapperFactory.create(request)
result = bootstrapper.bootstrap(request)

# Option 2 — Full pipeline: P0 scaffold -> A2C generation
workflow = BootstrapAndGenerateWorkflow(config=config)
result = workflow.execute(request, config)
```

### Single `scaffold-config.json` Drives Both Phases:

```json
{
  "scaffold": {
    "runtime": "python",
    "build_tool": "poetry",
    "project_name": "SettlementEngine",
    "platform": "aws"
  },
  "a2c": {
    "enabled": true,
    "project_type": "FastAPI Microservice",
    "mandatory_nfrs": [
      "Idempotency",
      "Observability",
      "TransactionalOutbox",
      "CircuitBreaker"
    ]
  }
}
```

### What P0 Generates in One `bootstrap()` Call:

* **Build and package definitions:** `pyproject.toml` / `pom.xml` / `go.mod`
* **Full directory tree structure:** Strict adherence to Clean Architecture layers (domain, application, infrastructure, interfaces)
* **Core environment configurations:** `.gitignore`, `.env.example`, `application.yml`
* **Project governance:** `README.md`, `LICENSE`
* **Enterprise containerization:** Multi-stage `Dockerfile` (non-root UID 1001, `HEALTHCHECK`), `.dockerignore`
* **Automation:** `Makefile`, `.github/workflows/` (OIDC, lint, test, security scan)

*See `base_project_bootstrapper.py` and `scaffold-config-schema.json` in this repository.*

---

## 🧬 G2C Extension — Generate-to-Class Framework

`G2C` is the declarative interface compilation layer of the stack. It uses E2A-governed generator classes to produce E2A abstract classes, A2C abstract classes, and their concrete inherited implementations via LLM.

**The framework stack is self-generating.**

### Four Generator Classes, One Unified Entry Point:

| Generator Class | Output Generated | P0 Scaffold Included? |
| :--- | :--- | :--- |
| `E2AAbstractClassGenerator` | `e2a_base.py` or `E2ABase.java` | No |
| `A2CAbstractClassGenerator` | `a2c_base.py` | No |
| `E2AInheritedClassGenerator` | Abstract class + project scaffold + concrete agent class | Yes |
| `A2CInheritedClassGenerator` | E2A + A2C abstract classes + scaffold + SDLC subclass | Yes |

### One Call, Complete Output:

```python
# DeveloperPlatformWorkflow chains all generators automatically
workflow = DeveloperPlatformWorkflow(config=config)
result = workflow.generate({
    'generator_type': 'e2a_inherited',
    'runtime':        'python',
    'agent_name':     'SettlementAgent',
    'user_prompt':    'SAP TM financial settlement agent with HMAC-SHA256 idempotency',
    'output_path':    './'
}, config)

# G2C automatically compiles:
# 1. Declarative OpenAPI/OData specs into Pydantic models
# 2. P0 scaffold workspace directory tree
# 3. Sealed SettlementAgent class extending BaseAgent
# Validates via GeneratorCriticAgent (score >= 0.75) before writing any file to disk.
```

**Runtime-Agnostic Compilation:** Generator classes are written in Python; generated output is Python, Java 21, Node.js, or Go based on `request['runtime']`. Zero generator code modifications are needed per runtime target.

*See `G2C_Framework_Reference.pdf` in this repository for the full specification.*

---

## 🔗 The Framework Ecosystem

A2C operates as a core pillar of the enterprise generative AI and distributed systems ecosystem:

* [**`e2a-framework`**](https://github.com/subhamviky/e2a-framework): The runtime governance substrate providing Template Method lifecycles, MCP execution harnesses, and distributed idempotency locks.
* [**`financial-settlement-platform`**](https://github.com/subhamviky/financial-settlement-platform): Java 21 / Spring Boot reference spike validating Saga orchestration, outbox CDC, and double-entry ledger posting.
* [**`order-to-cash-agentic-ai`**](https://github.com/subhamviky/order-to-cash-agentic-ai): 5-agent LangGraph platform demonstrating bounded context isolation and critic verification on AWS Bedrock.

---

## 👤 Author & Strategic Architecture Advisory

**Subham Gupta** — Staff Architect · Distributed Systems & Enterprise Agentic Governance  
13+ years building ledger-grade distributed systems at SAP scale.

[![LinkedIn](https://img.shields.io/badge/LinkedIn-Connect-0077B5?logo=linkedin)](https://linkedin.com/in/subham-gupta-0a05a058)
[![Email](https://img.shields.io/badge/Email-subhamviky@gmail.com-D14836?logo=gmail)](mailto:subhamviky@gmail.com)

---
*Trademarks: AWS, GCP, Azure, Anthropic, Claude, OpenAI, and SAP belong to their respective owners and are used purely for architectural reference and nominative identification.*
