# Changelog

## v1.2.0 — Declare it in the request; generate for E2A v1.2 (wave C)

Requires E2A `v1.2.0`.

### Added — declarations instead of patches (design note C-02)
- **App settings (A-3):** `a2c_sdlc.settings: [{name, default?, secret?}]` become Terraform variables, the runtime environment of the container or function and a Terraform test assertion per setting on AWS, GCP and Azure; a line in `.env.example`; `src/<package>/settings.py` (`load_settings()` fails at start-up naming the missing ones) or an `app:` section in Spring's `application.yml`. A secret is declared in the cloud secret store (Secrets Manager, Secret Manager, Key Vault) and referenced; Terraform never holds its value.
- **Contracts to models (A-5):** `a2c_sdlc.contracts: [path]` generates Pydantic models (`src/<package>/contracts/`) and a test that round-trips the schema's `examples`, or Java records with Jackson names (`<group>/contracts/`). A declared subset of JSON Schema (including the "present only when" `if/then/else` idiom); anything else is refused by name.
- **Maven coordinates (P-5):** `context.dependencies` entries `group:artifact[:version][@scope]`; short names stay Spring starters.
- **Monorepo layout (P-6):** `context.repository_layout: monorepo` or `aidlc-build --repository-layout monorepo` moves the generated workflows to the repository root as `<project>-<name>.yml`, scoped with `paths`, job working directories, `hashFiles` and the Maven cache path. The reusable scaffold workflow uses it (it used to park the workflows in `docs/`).
- **Upgrades (A-6):** every build writes `<project>/.a2c/manifest.json`; `aidlc-build --upgrade <project> [--baseline <dir>]` replaces the files you have not changed, adds new ones, writes `a2c-upgrade.patch` for the files you changed (`git apply --reject`), and never touches anything else.
- `smoke_test_declarations.py` (29 checks); CI job `declarations` (Terraform fmt and test on three clouds, generated tests, actionlint on a generated monorepo); the Java image of the `images` job now has a contract, a setting, Flyway and H2.

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
