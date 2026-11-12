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
CodeCriticAgent     ──▶ Model review AND a deterministic NFR-pattern check (comments ignored); the lower score must be >= 0.75
      │
      ▼
[ DevRequest ]      ──▶ (output: generated_* fields, critic_report, artifacts written into the P0 workspace)
```

The agents are implemented in [`a2c_base.py`](a2c_base.py) on top of E2A's `BaseAgent`, `BaseWorkflow`, `BaseToolService` and `BaseValidationService`; `SDLCWorkflow.execute(dev_request, config)` is the entry point. By default the agents run in the NFR-first order of the Reference (Requirements → IaC → CodeGen: observability → CI/CD → CodeGen: NFR module → CodeGen: business logic → Critic); `config['a2c_sequence'] = 'topology'` runs the five agents once each in the order above. A DevRequest is validated by `DevPlatformValidationService` before the workflow starts, and artifacts are written only after the critic passes, each write conditional on the version read at the start of the run.

Each agent reaches the model through the inherited E2A LLM service (`config['llm_service']`), never a provider SDK. A different model for a specific step — for example a cheaper one for `CodeCriticAgent` — is an explicit per-call argument (`critic.run(state, config, model_id=...)`), not a mutation of shared config.

---

## 🧱 Built on E2A

A2C is a meta-application of the [E2A Architecture Framework](https://github.com/subhamviky/e2a-framework). The same abstract class hierarchy that governs agentic AI systems is used here to build the developer platform that generates those systems.

* **The agent is governed by E2A:** Inherits single entry point execution, non-amplifiable credentials, and token budgets.
* **The model call is decoupled:** Generator and SDLC agents delegate inference to E2A's vendor-neutral `BaseLLMAgentService` — concurrency, RPM/TPM limits, DLP and typed failure semantics are inherited, and swapping provider is a binding change only.
* **Concurrent generation is bounded:** with a configured idempotency store, `generate()` and `bootstrap()` take an atomic claim per key (one owner, typed `replay` / `in_progress` / `conflict` / `recovery_required` outcomes), settle it on every exit path, and send every model call through `config['llm_service']`. Shared abstract classes carry a compare-and-set ownership record, so saga compensation never deletes one it did not create. See `a2c_concurrency.py` and the smoke tests below. These run against in-memory test doubles; they have not been validated against a live store, a live inference gateway or production load.
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
* **Core environment configurations:** `.gitignore`, `.env.example` (generated from the central `E2A_CONFIG` registry, so generated projects share one configuration model), `application.yml`
* **Project governance:** `README.md`, `LICENSE`
* **Enterprise containerization:** Multi-stage `Dockerfile` (non-root UID 1001, `HEALTHCHECK`), `.dockerignore`
* **Automation:** `Makefile`, `.github/workflows/` (OIDC, lint, test, security scan)

*See [`base_project_bootstrapper.py`](base_project_bootstrapper.py) and [`scaffold-config-schema.json`](scaffold-config-schema.json).*

---

## 🧬 G2C Extension — Generate-to-Class Framework

`G2C` is the declarative interface compilation layer of the stack. It uses E2A-governed generator classes to produce E2A abstract classes, A2C abstract classes, and their concrete inherited implementations via LLM.

**The framework stack is self-generating.**

### Four Generator Classes, One Unified Entry Point:

`E2AAbstractClassGenerator` emits the full E2A abstract set — now nine classes including `BaseLLMAgentService` — so generated agents get `config['llm_service']` delegation by construction. A repository that already holds an older `e2a_base.py` (no `BaseLLMAgentService`) should be treated as stale and regenerated before reuse; see [`docs/G2C_PHASE_TRIGGER_DECISION_REFERENCE.md`](docs/G2C_PHASE_TRIGGER_DECISION_REFERENCE.md).


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

# One call:
# 1. E2A base abstract class generated (abstract_class_source defaults to 'generate')
# 2. P0 scaffold, when request['scaffold'] is given (inline, inside the generator)
# 3. SettlementAgent class extending BaseAgent, written into the scaffold
# Every output passes GeneratorCriticAgent (score >= 0.75) before any file is written.
# Without config['llm_service'] the generators run in template mode (deterministic skeletons).
```

**Runtime-Agnostic Compilation:** Generator classes are written in Python; generated output is Python, Java 21, Node.js, or Go based on `request['runtime']`. Zero generator code modifications are needed per runtime target.

*See [`docs/G2C_FRAMEWORK_REFERENCE.md`](docs/G2C_FRAMEWORK_REFERENCE.md) for the full specification and [`docs/G2C_PHASE_TRIGGER_DECISION_REFERENCE.md`](docs/G2C_PHASE_TRIGGER_DECISION_REFERENCE.md) for which phases to run or skip for a given repository state.*

---

## 🗂️ Repository Layout

```
a2c-framework/
├── README.md · LICENSE
├── docs/                          A2C, G2C, G2C phase-trigger and P0 reference documents (.md, with Word copies)
│   └── design/                    HLD and LLD design documents with diagrams (p0/, g2c/, a2c/)
├── a2c_base.py                    A2C — DevRequest, SDLCAssistantAgent and specialists,
│                                  CodeCriticAgent, SDLCWorkflow, validation service, tools
├── base_project_bootstrapper.py   P0 — project bootstrap, BootstrapAndGenerateWorkflow
├── base_generator_agent.py · inherited_generator.py · generator_templates.py
├── e2a_abstract_class_generator.py · e2a_inherited_class_generator.py
├── a2c_abstract_class_generator.py · a2c_inherited_class_generator.py
├── generator_critic_agent.py · generator_factory.py
├── developer_platform_workflow.py · generator_api_router.py · typedicts.py      G2C
├── a2c_concurrency.py             claim store, shared-artifact ownership, deadlines
├── smoke_test_generator_concurrency.py    G2C/P0 concurrency (in-memory test doubles)
├── smoke_test_g2c_contract.py     G2C method contract: files, critic, chain, P0 inline, API
├── smoke_test_a2c.py              A2C workflow, critic, conditional writes, P0 -> A2C
├── smoke_test_aidlc_integration.py   E2A AI-DLC build over the real G2C, P0 and A2C
├── scaffold-config-schema.json
├── schemas/                       generator-config-schema.json
├── a2c_assets/                    prompts/ (versioned generator prompts) and templates/ (template mode)
├── a2c_template_llm.py · a2c_cli.py   A2C template mode and the `aidlc-build` command
└── examples/                      scaffold and generator config examples
```

Run the tests (the A2C and AI-DLC ones need `e2a-framework/reference` checked out next to this repository, or `E2A_REFERENCE_PATH` set; the router checks need `fastapi` and `httpx`): 

```bash
python smoke_test_generator_concurrency.py
python smoke_test_g2c_contract.py
python smoke_test_a2c.py
python smoke_test_aidlc_integration.py
python smoke_test_template_mode.py` covers v1.1.0 and v1.1.1: the G2C Java fix, P0 starters, template mode and `aidlc-build`.
```

All of them use in-memory test doubles; nothing has been validated against a live store, a live inference gateway or production load.

`e2a_base.py` is intentionally **not** duplicated here: the single source of truth is [`e2a-framework/reference/e2a_base.py`](https://github.com/subhamviky/e2a-framework/blob/main/reference/e2a_base.py). Generated projects import it from the resolved shared-abstractions package.

---

## 📐 Reference Documentation

| Document | Covers |
| :--- | :--- |
| [A2C Framework Reference](docs/A2C_FRAMEWORK_REFERENCE.md) | Multi-agent SDLC workflow, NFR injection, critic gates |
| [G2C Framework Reference](docs/G2C_FRAMEWORK_REFERENCE.md) | Generator classes and the unified `generate()` entry point |
| [G2C Phase Trigger Decision Reference](docs/G2C_PHASE_TRIGGER_DECISION_REFERENCE.md) | Which of the seven phases run or skip for a given repository state |
| [P0 Project Bootstrap Reference](docs/P0_FRAMEWORK_REFERENCE.md) | `bootstrap()`, `scaffold-config.json`, directory trees per runtime |
| [Design documents](docs/design/README.md) | HLD and LLD with diagrams for P0, G2C and A2C |

---

## 🔗 The Framework Ecosystem

A2C operates as a core pillar of the enterprise generative AI and distributed systems ecosystem:

* [**`e2a-framework`**](https://github.com/subhamviky/e2a-framework): The runtime governance substrate providing Template Method lifecycles, the vendor-neutral `BaseLLMAgentService`, MCP execution harnesses, and distributed idempotency locks.
* [**`capability-oriented-dsa`**](https://github.com/subhamviky/capability-oriented-dsa): governed algorithms with declared operations, used by the generated services for bounded matching and ranking.

**Built with A2C.** The three projects below began as architectural spikes (kept on their `spike/v1-original` branches) that informed this framework family. Their `main` branches are the completed projects: every service was generated by `aidlc-build` (P0 + G2C + A2C, template mode) from one request file, then completed by hand on the E2A contracts. The untouched scaffolds are on their `aidlc/*` branches.

| Project | Generated services | Target cloud (A2C landing zone) |
|---|---|---|
| [`financial-settlement-platform`](https://github.com/subhamviky/financial-settlement-platform) | `settlement-service` (Java 21, Maven), `audit-ai-service` (Python, Poetry) | Azure |
| [`aws-reconciliation-engine`](https://github.com/subhamviky/aws-reconciliation-engine) | `reconciliation-service` (Python, Lambda) | AWS |
| [`order-to-cash-agentic-ai`](https://github.com/subhamviky/order-to-cash-agentic-ai) | `o2c-agent-service` (Python, Cloud Run) | Google Cloud |

---

## 👤 Author & Strategic Architecture Advisory

**Subham Gupta** — Staff Architect · Distributed Systems & Enterprise Agentic Governance  
13+ years building ledger-grade distributed systems at SAP scale.

[![LinkedIn](https://img.shields.io/badge/LinkedIn-Connect-0077B5?logo=linkedin)](https://linkedin.com/in/subham-gupta-0a05a058)
[![Email](https://img.shields.io/badge/Email-subhamviky@gmail.com-D14836?logo=gmail)](mailto:subhamviky@gmail.com)

---
*Trademarks: AWS, GCP, Azure, Anthropic, Claude, OpenAI, and SAP belong to their respective owners and are used purely for architectural reference and nominative identification.*
