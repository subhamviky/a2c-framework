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

## P0 Extension — Project Bootstrap Framework

P0 extends A2C with Phase Zero scaffolding: generating everything a project needs *before* A2C generates business logic.

**Why a separate class (not an extension):** `bootstrap()` runs once per project at creation. `SDLCAssistantAgent.run()` runs whenever a new component is generated. Merging them would force re-scaffolding on every code generation call. The correct design: two independent classes composed via `BootstrapAndGenerateWorkflow`.

```python
# Option 1 — Bootstrap only
bootstrapper = ProjectBootstrapperFactory.create(request)
result = bootstrapper.bootstrap(request)

# Option 2 — Full pipeline: P0 scaffold -> A2C generation
workflow = BootstrapAndGenerateWorkflow(config=config)
result = workflow.execute(request, config)
```

**Single scaffold-config.json drives both phases:**

```json
{
  "scaffold": {
    "runtime": "python", "build_tool": "poetry",
    "project_name": "SettlementEngine", "platform": "aws"
  },
  "a2c": {
    "enabled": true, "project_type": "FastAPI Microservice",
    "mandatory_nfrs": ["Idempotency", "Observability"]
  }
}
```

**What P0 generates in one `bootstrap()` call:**
`pyproject.toml` / `pom.xml` / `go.mod` · Full directory tree · `.gitignore` · `.env.example` · `application.yml` · `README.md` · `LICENSE` · Multi-stage `Dockerfile` (non-root UID 1001, HEALTHCHECK) · `.dockerignore` · `Makefile` · `.github/workflows/`

See `base_project_bootstrapper.py` and `scaffold-config-schema.json` in this repo.

---

## G2C Extension — Generate-to-Class Framework

G2C is the top layer of the stack. It uses E2A-governed generator classes to produce E2A
abstract classes, A2C abstract classes, and their concrete inherited implementations via LLM.
**The framework stack is self-generating.**

**Four generator classes, one entry point:**

| Class | Generates | P0 scaffold? |
|---|---|---|
| `E2AAbstractClassGenerator` | `e2a_base.py` or `E2ABase.java` | No |
| `A2CAbstractClassGenerator` | `a2c_base.py` | No |
| `E2AInheritedClassGenerator` | Abstract class + project scaffold + agent class | Yes |
| `A2CInheritedClassGenerator` | E2A + A2C abstract classes + scaffold + SDLC subclass | Yes |

**One call, complete output:**
```python
# DeveloperPlatformWorkflow chains all generators automatically
workflow = DeveloperPlatformWorkflow(config=config)
result = workflow.generate({
    'generator_type': 'e2a_inherited',
    'runtime':        'python',
    'agent_name':     'SettlementAgent',
    'user_prompt':    'SAP TM financial settlement agent',
    'output_path':    './'
}, config)
# G2C generates: abstract base class, P0 scaffold, SettlementAgent class
# Validates via GeneratorCriticAgent (score >= 0.75) before writing any file
```

**Runtime-agnostic:** generator classes are Python; output is Python, Java, Node, or Go
based on `request['runtime']`. Zero generator code changes per runtime swap.

See `G2C_Framework_Reference.pdf` in this repo for the full specification.
---

**Author:** Subham Gupta — Staff Architect
[![LinkedIn](https://img.shields.io/badge/LinkedIn-Connect-0077B5?logo=linkedin)](https://linkedin.com/in/subham-gupta-0a05a058)
[![Email](https://img.shields.io/badge/Email-subhamviky@gmail.com-D14836?logo=gmail)](mailto:subhamviky@gmail.com)
