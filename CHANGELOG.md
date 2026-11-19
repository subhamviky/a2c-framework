# Changelog

## v1.5.2 — aidlc-change through the cloud account (hub design note AD-01, plan step 4)

Workflow only; no code change.

### Added
- **`aidlc-change.yml` signs in to Google Cloud through Workload Identity Federation** when `gcp_workload_identity_provider` and `gcp_service_account` are given (`google-github-actions/auth`, `id-token: write`), and sets `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION`. With the `google_vertex` profile the model is Gemini on Vertex AI in your project: no model-provider account and no stored key. The credentials file is excluded from the change (`.git/info/exclude`), so the clean-tree check still holds.

## v1.5.1 — aidlc-change for Java (hub design note AD-01, plan step 3)

Requires E2A `v1.6.1` (e2a-java `1.6.1` for Java projects). Additive.

### Added
- **`aidlc-change` on Maven projects built on e2a-java** (`a2c_change_java.py`):
  - A light Java reader (comments and literals masked, brace matching) indexes types and their members; a member's region starts at its Javadoc or annotations.
  - What e2a-java owns is its `final` methods, read with `javap` from the e2a-java jars the project's `pom.xml` names (`run()` on `BaseAgent`, `execute()` on `BaseWorkflow`); without them, A2C's older rule (`run`, `execute`, `retrieve` on a `Base*` class). The compiler enforces `final` too.
  - Edits replace one member or add members to a type; overloaded members are refused (replace the type's members one at a time); Java has no module-level region.
  - Maven compiles and tests every attempt (`mvn -B -q verify`; `test-compile` with `--no-tests`); a compile error goes back to the model like a failing test. The critic's Java rule refuses direct provider SDK imports and own semaphores or rate limiters.
- **Versions with a suffix**: `0.1.0-SNAPSHOT` names the next release `0.1.0`; a feature after release `0.1.0` makes it `0.2.0-SNAPSHOT`.
- **`aidlc-change.yml`** sets up Java and installs e2a-java at the version the project names.
- **`smoke_test_change_java.py`** (13 checks, real Maven builds), in CI.

## v1.5.0 — Changing existing code, and a developer's trail for every run (hub design note AD-01)

Requires E2A `v1.6.1`. Additive: `aidlc-build` without `--commit` behaves as before.

### Added
- **`aidlc-change`** (`a2c_change.py`): changes an existing Python E2A service from a prompt or a command.
  - Locates the code: an index of classes and methods, with the methods E2A owns taken from E2A's own conformance data; `--target path::Class.method` makes it exact.
  - Plans with the model, shows the plan, and waits for the developer (`--yes` in the workflow). A declaration change (a new agent, tool, contract, setting or dependency) is refused with the way to declare it: in the request, then `aidlc-build --upgrade --commit`.
  - Edits only inside the plan and only what a developer could edit: never a framework-owned method, `.a2c/`, `.env`, versions, dependencies or the changelog; Terraform, CI and Dockerfiles only with `--allow-infra`.
  - Verifies: compile, E2A conformance (no new findings), secret scan, the critic's concurrency checks, the project's tests (which must already pass on the base commit). Failures go back to the model, up to three attempts. Then nothing is committed: the files are restored, and `aidlc-change.patch` and `aidlc-change-report.json` are left for the developer.
  - The model is bound through E2A: `--llm profile:<name>` (any provider profile) or `replay:<file>` (recorded answers); `--record` saves a session's answers.
  - The same change on the same commit reuses its branch.
- **Provenance for every run** (`a2c_provenance.py`), for `aidlc-build --commit`, `aidlc-build --upgrade --commit` and `aidlc-change`:
  - **Author = the developer**: the checkout's git identity (`--author` may only restate it), or in a workflow the person who started the run, with the bot as committer. No developer, or a bot: refused.
  - **Trailers**: `Change-Id`, `Assisted-by: a2c-framework/<version>:<model>` (the Linux kernel's and Fedora's format), `AIDLC-Run` in a workflow, `Prompt-Sha256`; `Signed-off-by` only with `--signoff`; `Co-authored-by` for the tool only if the project's `.a2c/policy.json` asks for it.
  - **Branches**: `aidlc/<project>` (new), `aidlc-upgrade/<project>/<id>`, `aidlc-change/<project>/<id>`. A clean working tree is required.
  - **Change record** `.a2c/changes/<id>.json`: developer, base commit, prompt (secrets redacted, or only its hash with `prompt_storage: hash`), plan, tool and model, file hashes before and after, checks.
  - **Version and changelog**: the version of the next release, from the kind of change (a project never released keeps its version); a Keep a Changelog entry under *Unreleased*. Tags stay manual.
  - **Manifest origins**: `.a2c/manifest.json` records which files were generated and which changed; `--upgrade` never replaces a changed file.
  - **Audit event**: one JSON line per run on the `a2c.audit` logger and stderr (`AIDLC-AUDIT`), with actor, `actor_is_agent`, `initiated_by`, change id, model, outcome.
- **`a2c_signed_push`**: recreates a workflow's commit through GitHub's API (author, message and trailers unchanged, no committer given) so that GitHub signs it.
- **Workflow `aidlc-change.yml`** (reusable), and `aidlc-scaffold.yml` now commits as the developer, pushes signed (`signed: false` to opt out) and keeps the run's log as an artifact.
- **Tests**: `smoke_test_provenance.py` (47 checks) and `smoke_test_change.py` (30 checks), in CI.

### Not changed
- Java projects: `aidlc-change` refuses them, naming v1.5.1. Provenance (`--commit`) already covers Java builds.
- The signing of workflow commits by GitHub's API is tested against a fake API; it is confirmed on the first live run.

## v1.4.0 — Generated services bind their model from a profile (hub design note MP-03, P27)

Requires E2A `v1.6.1` (and, for Java, e2a-java `1.6.1`, installed from E2A's tag).

### Added
- **A composition root in every generated Python E2A service:** `src/<package>/services/bindings.py`.
  - `bindings()` binds the model and the other E2A seams with `e2a.bindings_from_profile(...)`, once, with `verify=True`.
  - `service_config()` returns the config for `workflow.execute()` / `agent.run()`: the bound `llm_service` and engines, the profile's settings, and the service's tools.
  - The profile is `E2A_PROVIDER_PROFILE`, else the request's default. No generated source constructs a model service by name.
- **`a2c_sdlc.provider_profile`** (default `simulated`, E2A's built-in profile): the deployment's default profile, written into the composition root.
- **`a2c_sdlc.provider_requirement`**: a pip requirement added to the generated project, for the provider package whose profile is named (for example `e2a-managed-providers[anthropic-aws] @ git+...`).
- **Generated tests:** `tests/test_bindings.py` (the composition root binds from a profile); `tests/test_workflow.py` binds the model from the `simulated` profile, so the tests need no provider account whatever profile the deployment uses.
- **`smoke_test_profile_binding.py`** (14 checks), which also runs the generated project's own tests.

### Changed
- **Pins:** `e2a-framework` `@v1.6.1` in `pyproject.toml` and in generated Python projects (`a2c_cli.E2A_REF`); CI checks out E2A `v1.6.1`; `g2c_java12.E2A_JAVA_VERSION` is `1.6.1`. E2A v1.4 to v1.6.1 are additive, and every existing smoke test passes unchanged on v1.6.1.

### Not changed
- **Java services:** e2a-java has no bindings yet, so `provider_profile` on a Java service is refused, naming why. Generated Java tests keep `SimulatedLlmService`.
- **A2C's own generation model** (`a2c_template_llm.build_template_llm`): the deterministic template service A2C itself runs on is not a deployment choice.

## v1.3.0 — v1.1 generation removed (design note V13-01)

Requires E2A `v1.3.0` (and, for Java, e2a-java `1.3.0`, installed from E2A's tag).

### Removed
- **`"e2a_contract": "1.1"`** for `e2a_inherited`, Python and Java. A request with it is refused before anything is written: `e2a_contract 1.1 was removed in A2C v1.3`. E2A v1.3 refuses the v1.1 hooks at class definition, so the generated code could not run.
- **The Java v1.1 skeleton** (`E2ABase.java` copied into the project, with an inherited class on it). Java agents are generated against e2a-java.
- **The v1.2.2 build-report warnings** about both: there is nothing left to warn about.
- **The v1.1 branch of the Python inherited template** (`generator_templates.inherited`): both kinds now emit the v1.2 hooks.

### Changed
- **Java defaults to `"e2a_contract": "1.2"`**, like Python: a Java `e2a_inherited` request without the field gets the e2a-java project (agents, workflow, governance, tools, `AgentContract` tests, a pom on `e2a-core`/`e2a-test`, CI and a Dockerfile that install e2a-java first).
- **Pins:** `e2a-framework` `@v1.3.0` in `pyproject.toml`; CI checks out E2A `v1.3.0`; `g2c_java12.E2A_JAVA_VERSION` is `1.3.0`.
- **Smoke tests:** the abstract-chain checks (shared base ownership, replay, compensation, the AI-DLC build) run on `a2c_inherited`, the one type that still chains the E2A and A2C base classes. `e2a_inherited` imports the installed `e2a`, so it has no base to share.

### Added
- **CI:** `python -m e2a.conformance` over A2C's sources; strict by default in E2A v1.3, so an R2 or D1 finding fails the job.

### Not changed
- `a2c_inherited`, the standalone `e2a_abstract` / `a2c_abstract` generators (Python, Java, Node, Go), and `SDLCWorkflow`'s v1.1 workflow form, which E2A keeps.

## Unreleased — CI fix (released with v1.3.0)

- **The CI guard** (v1.2.2) matched any line containing "removed in v1.3". That includes the warning A2C's own build report gives on purpose for a Python `"e2a_contract": "1.1"` request, so `smoke_test_g2c_v12` failed the job. It now matches E2A's adapter warning ("uses the v1.1 keyword signature"). CI only: the package is unchanged.

## v1.2.2 — Preparing for v1.3 (design note V13-01)

Requires E2A `v1.2.2`. Nothing is removed.

### Changed
- **A2C's own SDLC agents** (`RequirementsAgent`, `CodeGenAgent`, `IaCAgent`, `CICDAgent`, `CodeCriticAgent`, and `SDLCAssistantAgent`) use the E2A v1.2 hooks (`state, ctx`): no v1.1 adapter runs in an A2C build.
  - `approved_clouds` is read with `ctx.setting()`.
  - The `approved_agents` checks are gone: they read a registry key whose default is `[]`, and E2A v1.2's governance is where agents are allowed.
- **The four generator tools** implement `_get_endpoint`: no conformance D1 finding.
- **G2C:** an `a2c_inherited` (SDLC) agent is generated on the v1.2 hooks.

### Added
- **The build report's `warnings`** say what v1.3 removes:
  - `"e2a_contract": "1.1"` for Python (E2A v1.3 no longer runs v1.1 hooks);
  - the Java v1.1 skeleton (`E2ABase.java`): A2C v1.3 defaults Java to `"1.2"`.
- **CI:** the smoke tests run with warnings shown and fail if any uses E2A's v1.1 adapters.
- **Smoke tests:** `smoke_test_g2c_v12.py` has 19 checks and `smoke_test_java12.py` 15.

### Not changed
- `SDLCWorkflow` keeps the v1.1 workflow form (a graph and `_get_agent`): E2A never deprecated it, and the SDLC chain's regeneration loop is not a declared `Steps` workflow.

## Documents for v1.2.1 (docs only, merged after the v1.2.1 tag)

- **A2C design:** new 5.8, evaluation sets and the release gate.
- **G2C design:** new 5.7, Java on e2a-java.
- **P0 design:** the `evaluation`, `release_gate` and `e2a_java` request fields.
- **References:** A2C reference section 10; G2C reference section 19.
- **Word documents:** the three design `.docx` files regenerated.

## v1.2.1 — Evaluation sets and E2A's release gate; Java on e2a-java

Requires E2A `v1.2.2`.

### Added — evaluation sets (design note C-04, D-2)
- **`a2c_sdlc.evaluation: {set, redteam, threshold}`** (Python, E2A v1.2) generates:
  - `src/<package>/release/gate.py`, a `ProjectReleaseGate` subclass whose `_score_case` / `_probe` stubs fail until written;
  - the evaluation files, with one example case each;
  - a release-gate step in the CI, with the declared threshold.
- **Without an evaluation**, an E2A v1.2 service's CI runs E2A's generic gate (`python -m e2a.release`).
- **Phase C** (`aidlc-build`) uses E2A's checks:
  - E2A's secret patterns;
  - for an E2A v1.2 project, strict `e2a.conformance` and `compileall` over `src/`;
  - a declared evaluation set's shape (the cases are scored by the project CI).

### Added — G2C generates Java on E2A v1.2 (design note D-01, G-4)
- **`"e2a_contract": "1.2"` on a Java request**, an opt-in (the Java default stays `1.1`), generates against e2a-java (`com.subhamviky.e2a`):
  - one class per agent, with hooks from `kind`, `reads`, `writes` and `output_schema`;
  - the declared workflow (`Steps`, `Step`, `Route`);
  - `ServiceGovernance` (capacity, firewall, approval);
  - tool stubs (`material` for writes);
  - an `AgentContract` JUnit test per agent.
- **No `E2ABase.java` is generated.** P0 adds `e2a-core` and `e2a-test` as Maven coordinates and installs e2a-java from E2A's tag in the generated CI and Dockerfile.
- **The critic:** it checks the Java v1.2 hooks; compilation is the project's `mvn verify`, against e2a-java.

### Also
- **New smoke tests:**
  - `smoke_test_evaluation.py` (17 checks);
  - `smoke_test_java12.py` (14 checks, including `mvn verify` of a generated three-agent Java project);
- **Updated:** `smoke_test_g2c_v12.py` checks the remaining Java refusal (a stage e2a-java does not have).
- **CI:** installs e2a-java and runs both new tests. The E2A pin is `v1.2.2`. New example: `examples/requests/agents-java.json`.

## v1.2.0 — Declare it in the request; generate for E2A v1.2 (wave C)

Requires E2A `v1.2.0`.

### Added — declarations instead of patches (design note C-02)
- **App settings (A-3):** `a2c_sdlc.settings: [{name, default?, secret?}]` become Terraform variables, the runtime environment of the container or function and a Terraform test assertion per setting on AWS, GCP and Azure; a line in `.env.example`; `src/<package>/settings.py` (`load_settings()` fails at start-up naming the missing ones) or an `app:` section in Spring's `application.yml`. A secret is declared in the cloud secret store (Secrets Manager, Secret Manager, Key Vault) and referenced; Terraform never holds its value.
- **Contracts to models (A-5):** `a2c_sdlc.contracts: [path]` generates Pydantic models (`src/<package>/contracts/`) and a test that round-trips the schema's `examples`, or Java records with Jackson names (`<group>/contracts/`). A declared subset of JSON Schema (including the "present only when" `if/then/else` idiom); anything else is refused by name.
- **Maven coordinates (P-5):** `context.dependencies` entries `group:artifact[:version][@scope]`; short names stay Spring starters.
- **Monorepo layout (P-6):** `context.repository_layout: monorepo` or `aidlc-build --repository-layout monorepo` moves the generated workflows to the repository root as `<project>-<name>.yml`, scoped with `paths`, job working directories, `hashFiles` and the Maven cache path. The reusable scaffold workflow uses it (it used to park the workflows in `docs/`).
- **Upgrades (A-6):** every build writes `<project>/.a2c/manifest.json`; `aidlc-build --upgrade <project> [--baseline <dir>]` replaces the files you have not changed, adds new ones, writes `a2c-upgrade.patch` for the files you changed (`git apply --reject`), and never touches anything else. Proven on reconciliation and settlement (both scaffolded with v1.1.0).
- **Settings from your own Terraform:** `{"name": "TABLE_NAME", "terraform": "aws_dynamodb_table.recon.name"}` (reconciliation's table).

### Added — G2C generates E2A v1.2, several agents at once (design note C-01)
- **E2A v1.2 contract (G-3):** a Python `e2a_inherited` agent targets E2A v1.2 by default (`harness.e2a_contract`, `"1.1"` still selectable): hooks declare only what they use (`_prepare(state, ctx, io_read)`, `_act(state, ctx, io_modify)`, …), `from e2a import BaseAgent`. Java stays on 1.1 and refuses `1.2` with a clear message (e2a-java is wave D). A2C's own SDLC agents are unchanged.
- **Several agents (G-1):** `harness.agents`, `harness.workflow` (declared `Step` / `Route` steps) and `harness.governance.stages` generate every agent, the workflow, the governance class (stages and `tool_policy`), the validation service (a validator stub per agent) and the tool stubs (`material` for writes).
- **Typed hooks (G-2):** `kind: deterministic` → no model step; `reads` → `_prepare` with `io_read`; `writes` → `_act` with `io_modify`; `output_schema` → a Pydantic model that `_evaluate_output` validates. The `approved_agents` check is no longer generated.
- **Tests (A-8):** `AgentContract` per agent, the conformance rules (strict), and one request through the workflow with the simulated model (X-2). The G2C critic checks the v1.2 hooks and runs `e2a.conformance`.

### Removed
- **The application-service module (A-4):** `generated/service.py` / `<Project>Service.java` are no longer generated (no project used them); the NFR and observability modules stay and the critic reviews them. A2C runs 6 agent steps instead of 7.

### Also
- `smoke_test_declarations.py` (32 checks), `smoke_test_g2c_v12.py` (17 checks); CI job `declarations` (Terraform fmt and test on three clouds, generated tests, actionlint on a generated monorepo); the Java image of the `images` job now has a contract, a setting, Flyway and H2.

### Fixed
- `CodeCriticAgent`'s input validator still required `generated_code` (the removed application-service module); it now requires `generated_nfr_module`. `smoke_test_a2c.py` checks it (26 checks).

### Docs
- **Design documents** (A2C, G2C, P0): updated for v1.2: declarations and upgrades (A2C 5.6, 5.7, 8.8), E2A v1.2 generation and several agents (G2C 5.6, 8.6), the new ScaffoldRequest and handoff fields (P0), the six-step chain, verification, observations and traceability. New diagrams `10_declarations`, `11_upgrade` (A2C) and `13_v12_generation` (G2C); updated `04_workflow`, `07_nfr_first` and `04_typeddicts`; `docs/design/common/style.puml` restored.
- **Word documents:** the three `*_Framework_Design_Document.docx` are regenerated from the Markdown in the same house style (cover, contents with page numbers, headers and footers, tables, figures).
- **References:** A2C (what v1.2 changes; section 9, declarations and upgrades), P0 (what v1.1.2 and v1.2 add), G2C (section 18, E2A v1.2 generation; the v1.2 critic rule), Phase Trigger Decision (names and v1.2 note).

## v1.1.2 — Fixes from the Order-to-Cash projects

### Fixed
- **P0 author (P-1):** generated `pyproject.toml` no longer hard-codes an author; `context.authors` is written when given, otherwise `authors = []`.
- **One service port (P-2):** `context.port` (default 8000 for Python, 8080 for Java) drives the Dockerfile's `EXPOSE`, health check and server command, and A2C's Azure/GCP `container_port`. They disagreed before (8000 vs 8080).
- **AWS Lambda handler (A-1):** the Terraform default is `<package>.lambda_entry.handler`; P0 generates `lambda_entry.py` (Mangum) and adds `mangum` for Python services on AWS.
- **GCP instances (A-2):** `max_instance_count` is the variable `max_instances` (default 3).

### Added
- `context.include_paths` (P-3): extra folders copied into the Python image (for example `policies`, `knowledge`).
- CI job `images` (P-4): generates a Python (GCP) and a Java (Azure) service, builds both images, starts them and probes their health endpoints.
- Reusable workflow `.github/workflows/aidlc-scaffold.yml` (A-7): projects call it with `uses: subhamviky/a2c-framework/.github/workflows/aidlc-scaffold.yml@v1.1.2` instead of copying it.
- `examples/requests/`: the two requests the image job builds.
- `smoke_test_template_mode.py`: 31 checks (authors, port, include paths, Lambda entry, handler default, GCP variable).

### Changed
- Requires E2A `v1.1.2`.

### Compatibility
- Requests without the new fields behave as before, except that the author is no longer filled in and the Azure/GCP `container_port` default for Python services is now 8000 (the port the Python image really serves).

## v1.1.1 — Container and CI upkeep

### Fixed
- **P0 Python Dockerfile:** the virtual environment is built in `/app` (where the runtime image uses it) instead of `/build`. A venv copied to another path keeps the old interpreter path in its scripts, so `uvicorn` failed with `not found` and the container exited at start.

### Changed
- Requires E2A `v1.1.1` (propagation fixes).
- Generated workflows (P0 `ci.yml`, A2C `delivery.yml`) and this repository's CI use Node-24 action versions: `actions/checkout@v6`, `actions/setup-python@v6`, `actions/setup-java@v5`, `hashicorp/setup-terraform@v4`.

### Added
- `smoke_test_template_mode.py`: a check that the P0 Python Dockerfile builds the venv at its runtime path (22 checks).

## v1.1.0 — Template mode and consumable packaging

### Added
- `pyproject.toml`: installs as `a2c-framework` (depends on `e2a-framework` v1.1.0) with the `aidlc-build` command.
- `a2c_template_llm.py`: A2C/G2C template mode through the E2A LLM boundary (deterministic, offline).
- `a2c_cli.py`: `aidlc-build` runs the E2A AI-DLC pipeline for one service; `ProjectStaticPipeline` gives Phase C real checks (secret scan, entry-point contract, required artifacts, terraform fmt, optional tests).
- `a2c_assets/templates/`: Terraform for AWS, GCP and Azure with `terraform test` files, a delivery workflow, NFR code modules for Python and Java.
- P0 `_generate_starter_files()` (Step 13b): entry point, first test, CI, dev container and compose file for Python and Java.
- `smoke_test_template_mode.py` (21 checks) and a GitHub Actions workflow.

### Changed
- Prompts moved from `prompts/` to `a2c_assets/prompts/` (the loader still honours `prompt_dir` and `GENERATOR_PROMPT_DIR`).

### Fixed
- G2C Java: hooks are camelCase in base and subclass, subclasses implement every hook, generated abstracts are placed in the Maven tree; the output compiles.
- G2C critic: Java output is compiled with `javac` when available; a compile error scores 0.0.
- P0 Python: dependency constraints and extras are kept; git dependencies are supported; the Dockerfile installs with Poetry 2 (`--only main --no-root`) and its health check no longer needs `curl`.
