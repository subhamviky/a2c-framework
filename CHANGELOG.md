# Changelog


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
