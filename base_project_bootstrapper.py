# base_project_bootstrapper.py
# P0 — Project Bootstrap Extension for the A2C Framework
# Phase Zero scaffolding: project structure, build manifest, git config,
# env templates, Docker, and Makefile — before A2C generates business logic.
#
# Architecture decision: New class alongside A2C (not an extension of it).
# Both can be called independently OR composed via BootstrapAndGenerateWorkflow.
# Follows the same E2A Template Method Pattern: one PUBLIC entry point,
# PROTECTED domain hooks, PRIVATE framework internals.
#
# github.com/subhamviky/a2c-framework
# Author: Subham Gupta, Staff Architect

import os
import json
import re
import uuid
import time
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional

from a2c_concurrency import ClaimGuard, fingerprint_of, run_coro_sync, status_of
from a2c_evaluation import ci_step, example_redteam, example_set, gate_module, normalize_evaluation
from a2c_contracts import Contract, java as contract_java, module_name, python as contract_python, python_test as contract_python_test
from a2c_settings import env_example, java_yaml, normalize as normalize_settings, python_module, python_test

logging.basicConfig(level=logging.INFO)


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  TypedDicts                                                              ║
# ╚══════════════════════════════════════════════════════════════════════════╝

from typing import TypedDict

class ScaffoldRequest(TypedDict, total=False):
    """
    Typed input to BaseProjectBootstrapper.bootstrap().
    Resolved from JSON file, natural-language prompt, or inline dict.

    Resolution chain (same as E2A config):
      request fields > _apply_policy injection > env variable > hardcoded default
    """
    # ── Source ──────────────────────────────────────────────────────────────
    source: str           # 'json' | 'prompt' | 'inline'  (default: 'inline')
    config_path: str      # path to scaffold-config.json   (required if source='json')
    prompt: str           # free-text description           (required if source='prompt')
    resolved_from: str    # written on resolution: 'json' | 'prompt' (source becomes 'inline')
    tenant_id: str        # scopes the idempotency claim; copied into dev_request

    # ── Runtime ─────────────────────────────────────────────────────────────
    runtime: str          # 'python' | 'java' | 'node' | 'go'
    runtime_version: str  # '3.12'   | '21'   | '20'  | '1.22'

    # ── Platform ────────────────────────────────────────────────────────────
    platform: str         # 'aws' | 'gcp' | 'azure' | 'standalone'

    # ── Project identity ────────────────────────────────────────────────────
    project_name: str     # PascalCase:  'SettlementEngine'
    package_name: str     # Python only: 'settlement_engine'  (snake_case)
    group_id: str         # Java only:   'com.company.domain'
    artifact_id: str      # Java only:   'settlement-engine'  (kebab-case)

    # ── Build tooling ───────────────────────────────────────────────────────
    build_tool: str       # 'poetry' | 'pip' | 'maven' | 'gradle' | 'npm' | 'go_modules'

    # ── Project type (drives directory structure) ────────────────────────────
    project_type: str     # 'fastapi_microservice' | 'spring_boot' | 'lambda'
                          # | 'langgraph_agent'    | 'library'

    # ── Dependencies ────────────────────────────────────────────────────────
    dependencies:     List[str]   # runtime deps  e.g. ['fastapi>=0.111', 'pydantic>=2.7']
    dev_dependencies: List[str]   # dev/test deps  e.g. ['pytest>=8', 'ruff>=0.4']

    # ── Java-specific ────────────────────────────────────────────────────────
    spring_boot_version: str   # '3.3.0'
    java_source_version: str   # '21'
    packaging: str             # 'jar' | 'war'

    # ── Python-specific ──────────────────────────────────────────────────────
    python_requires: str       # '>=3.12'

    # ── Output options ───────────────────────────────────────────────────────
    output_path:      str    # './' | '/path/to/output'   (default: './')
    license:          str    # 'Apache-2.0' | 'MIT' | 'PROPRIETARY'
    git_init:         bool   # True  → generate .gitignore + .gitattributes
    include_docker:   bool   # True  → generate Dockerfile + .dockerignore
    include_makefile: bool   # True  → generate Makefile
    # v1.1.2
    authors:          List[str]  # ['Name <email>'] written to pyproject.toml; empty when absent
    port:             int        # service port: Dockerfile, health check, A2C Terraform (python 8000, java 8080)
    include_paths:    List[str]  # extra folders copied into the image, e.g. ['policies', 'knowledge']
    # v1.2.1 (C-04)
    evaluation:       dict       # {set, redteam, threshold}: a generated release gate, eval files, CI step
    release_gate:     bool       # True → the CI runs E2A's release gate (generic stages); set by aidlc-build for E2A v1.2
    e2a_java:         str        # e2a-java version (D-01): the Java CI and Dockerfile install it from E2A's tag

    # ── Written by bootstrapper (do not supply) ──────────────────────────────
    scaffold_key:      str        # idempotency key: name:runtime:build_tool:platform
    scaffolded_files:  List[str]  # absolute paths of every file created
    scaffold_plan:     List[dict] # [{step, file, description}] — observability
    errors:            List[str]  # error accumulator


class ScaffoldResult(TypedDict, total=False):
    """
    Output from BaseProjectBootstrapper.bootstrap().
    When config['a2c']['enabled'] is True, dev_request is populated
    for direct handoff to SDLCAssistantAgent or SDLCWorkflow.
    """
    success:              bool
    scaffold_key:         str
    project_root:         str         # absolute path to project root
    scaffolded_files:     List[str]   # all created file paths
    build_manifest_path:  str         # pom.xml | pyproject.toml | go.mod
    readme_path:          str
    trace_id:             str
    latency_ms:           float
    errors:               List[str]
    dev_request:          Optional[dict]  # A2C DevRequest — populated on handoff
    status:               str         # scaffolded | replay | in_progress | conflict |
                                      # recovery_required | failed_final
    replayed:             bool        # True when a stored result is returned


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  Request resolution (shared by bootstrap() Step 1 and the factory)       ║
# ╚══════════════════════════════════════════════════════════════════════════╝

def _load_json_scaffold(config_path: str) -> dict:
    """Read scaffold-config.json; the 'scaffold' section (or the whole file)."""
    with open(config_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return dict(data.get('scaffold', data))


def _load_prompt_scaffold(prompt: str, config: dict) -> dict:
    """
    Parse a ScaffoldRequest from a natural-language prompt. The model call goes
    through the E2A inference service bound at config['llm_service'] (a
    BaseLLMAgentService); P0 holds no provider SDK or credentials. Override the
    model for this step with config['model_id'].
    """
    config = config or {}
    service = config.get('llm_service')
    if service is None:
        raise ValueError(
            "source='prompt' requires config['llm_service'] (a BaseLLMAgentService "
            "subclass). Provide it, or use source='json' or source='inline'.")
    messages = [
        {'role': 'system', 'priority': 0, 'content':
            'Return ONLY one JSON object matching the ScaffoldRequest schema. No prose, '
            'no code fences. Use only these keys: ' + ', '.join(ScaffoldRequest.__annotations__)},
        {'role': 'user', 'content': prompt},
    ]
    result = run_coro_sync(service.process_inference(
        messages, config=config, model_id=config.get('model_id'),
        tenant_id=config.get('tenant_id', 'p0'), response_schema=ScaffoldRequest))
    if result.get('status') == 'FAILED':
        raise RuntimeError(f"Prompt resolution failed: {result.get('error')}")
    parsed = result.get('structured_output')
    if parsed is None and result.get('text'):
        try:
            parsed = json.loads(result['text'])
        except json.JSONDecodeError:
            parsed = {'parse_error': True, 'raw': result['text']}
    parsed = parsed or {}
    if 'parse_error' in parsed:
        raise ValueError(f"Model did not return valid JSON: {parsed.get('raw')!r}")
    unknown = set(parsed) - set(ScaffoldRequest.__annotations__)
    if unknown:
        raise ValueError(f'Unknown ScaffoldRequest fields from model: {sorted(unknown)}')
    return dict(parsed)


def resolve_scaffold_request(request: dict, config: dict = None) -> dict:
    """
    Resolve source='json' | 'prompt' into an inline ScaffoldRequest.
    Priority: inline fields > loaded fields. Returns a new dict with
    source='inline' and resolved_from set; inline requests are returned as a copy.
    """
    request = dict(request or {})
    src = request.get('source', 'inline')
    if src == 'json':
        loaded = _load_json_scaffold(request['config_path'])
    elif src == 'prompt':
        loaded = _load_prompt_scaffold(request['prompt'], config or {})
    else:
        return request
    inline = {k: v for k, v in request.items() if k not in ('source', 'config_path', 'prompt')}
    merged = {**loaded, **inline}
    merged.pop('source', None)
    merged.update(source='inline', resolved_from=src)
    return merged


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  BaseProjectBootstrapper — Abstract Class                                ║
# ╚══════════════════════════════════════════════════════════════════════════╝

class BaseProjectBootstrapper(ABC):
    """
    Abstract base class for project scaffolding.  Phase Zero of the A2C pipeline.

    Single public entry point: bootstrap(request, config) -> ScaffoldResult

    Access modifier system (mirrors E2A):
      PUBLIC    bootstrap()                           — called by app code / workflow
      PROTECTED _validate_request()                  — check required fields
      PROTECTED _resolve_config()                    — load from JSON / prompt
      PROTECTED _plan_scaffold()                     — build ordered task list
      PROTECTED _scaffold_structure()                — create directory tree
      PROTECTED _generate_build_manifest()           — pom.xml / pyproject.toml
      PROTECTED _generate_dependency_config()        — requirements.txt (optional)
      PROTECTED _generate_git_config()               — .gitignore / .gitattributes
      PROTECTED _generate_env_templates()            — .env.example / application.yml
      PROTECTED _generate_readme_scaffold()          — README.md skeleton
      PROTECTED _generate_license()                  — LICENSE file
      PROTECTED _generate_docker_config()            — Dockerfile + .dockerignore
      PROTECTED _generate_makefile()                 — Makefile
      PROTECTED _validate_output()                   — confirm required files exist
      PROTECTED _handle_error()                      — error handler
      PRIVATE   __load_json_config()                 — JSON file reader
      PRIVATE   __load_prompt_config()               — LLM-based prompt parser
      PRIVATE   __write_file()                       — idempotent file writer
      PRIVATE   __create_directory()                 — mkdir -p
      PRIVATE   __generate_scaffold_key()            — business idempotency key
      PRIVATE   __is_already_scaffolded()            — idempotency check
      PRIVATE   __resolve_output_path()              — output path resolution
      PRIVATE   __write_build_manifest()             — runtime-aware manifest writer
      PRIVATE   __build_dev_request()                — A2C handoff payload builder

    Class variables:
      bootstrapper_name : str  — governance key, set in every subclass
      idempotency       : bool — default True; same scaffold_key = skip
    """

    bootstrapper_name: str = 'BaseProjectBootstrapper'
    idempotency: bool = True

    APPROVED_RUNTIMES: List[str]  = ['python', 'java', 'node', 'go']
    APPROVED_PLATFORMS: List[str] = ['aws', 'gcp', 'azure', 'standalone']
    APPROVED_BUILD_TOOLS: Dict[str, List[str]] = {
        'python': ['poetry', 'pip'],
        'java':   ['maven', 'gradle'],
        'node':   ['npm', 'yarn'],
        'go':     ['go_modules'],
    }
    MANIFEST_FILENAMES: Dict[tuple, str] = {
        ('python', 'poetry'): 'pyproject.toml',
        ('python', 'pip'):    'setup.cfg',
        ('java',   'maven'):  'pom.xml',
        ('java',   'gradle'): 'build.gradle',
        ('node',   'npm'):    'package.json',
        ('node',   'yarn'):   'package.json',
        ('go',     'go_modules'): 'go.mod',
    }

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}

    # ──────────────────────────────────────────────────────────────────────────
    # PUBLIC — single entry point
    # ──────────────────────────────────────────────────────────────────────────

    def bootstrap(
        self,
        request: ScaffoldRequest,
        config: Dict[str, Any] = None,
        **kwargs
    ) -> ScaffoldResult:
        """
        Public entry point.  Never override in subclasses.

        Internal sequence (16 steps — fixed):
          1  Resolve config      load from JSON or prompt if source != 'inline'
          2  Validate request    required fields, approved runtime/platform/build_tool
          3  Idempotency check   skip if scaffold_key already scaffolded
          4  Plan scaffold       build ordered [{step, file, description}] task list
          5  Directory structure create project directory tree
          6  Build manifest      pyproject.toml | pom.xml | go.mod
          7  Dependency config   requirements.txt (pip only; others embed in manifest)
          8  Git config          .gitignore + .gitattributes
          9  Env templates       .env.example | application.yml
          10 README scaffold     README.md with project name, badges, structure tree
          11 LICENSE file        Apache-2.0 | MIT | skip if PROPRIETARY
          12 Docker config       Dockerfile (multi-stage) + .dockerignore
          13 Makefile            common commands: install, test, lint, build, run
          14 Validate output     confirm build_manifest_path + readme_path created
          15 Latency SLO         warn if > max_latency_ms (default 10,000 ms)
          16 Observability log   structured JSON: bootstrapper, key, latency, file count
        """
        config  = config or self.config or {}
        request = dict(request or {})          # never mutate the caller's request
        trace_id = str(uuid.uuid4())
        start    = time.time()
        result: ScaffoldResult = {
            'success': False, 'trace_id': trace_id,
            'scaffolded_files': [], 'errors': []
        }
        guard = None
        writing_started = False
        output_invalid = False

        try:
            # Step 1 — resolve
            src = request.get('source', 'inline')
            if src in ('json', 'prompt'):
                request = self._resolve_config(request, config, **kwargs)

            # Step 2 — validate
            if not self._validate_request(request, config, **kwargs):
                raise ValueError(
                    f'[{self.bootstrapper_name}] Validation failed — check required '
                    'fields (runtime, platform, build_tool, project_name and the '
                    "runtime-specific ones); the log names what is missing"
                )

            # Step 3 — idempotency. With a store configured the ATOMIC CLAIM is the
            # authority (P0 Framework Reference 4.1); the directory check below is only
            # a fast path beneath it. Without a store the guarantee is single-process.
            key = self.__generate_scaffold_key(request)
            request['scaffold_key'] = key
            store = (config.get('scaffold_idempotency_store')
                     or config.get('idempotency_store'))
            # Claims are namespaced per framework ('p0:'), so a composing caller
            # that claims a similarly shaped key in the same store (AI-DLC's
            # project:runtime:build_tool:platform) never collides with P0.
            claim_key = f'p0:{key}' if self.idempotency else f'p0:{key}#rescaffold'
            guard = ClaimGuard(store, claim_key,
                               request.get('tenant_id') or config.get('tenant_id'),
                               fingerprint_of(request), config,
                               lease_seconds=float(config.get('claim_lease_seconds', 300)))
            claim = guard.acquire()
            if not guard.owned:
                return self.__not_owner(claim, key, result)
            if self.idempotency and self.__is_already_scaffolded(request, config):
                # Fast path: the target directory (resolved exactly as Step 5 would
                # resolve it) already holds a project. Return enough for the caller to
                # continue: the project root and, when enabled, the A2C hand-off.
                logging.info(f'[{self.bootstrapper_name}] Skip — already scaffolded: {key}')
                root = self.__project_dir(request, config)
                result.update({'success': True, 'scaffold_key': key, 'status': 'replay',
                               'replayed': True, 'project_root': str(root.resolve())})
                a2c_cfg = config.get('a2c', {})
                if a2c_cfg.get('enabled', False):
                    result['dev_request'] = self.__build_dev_request(
                        request, a2c_cfg, config, str(root.resolve()))
                guard.succeed(dict(result))
                return result

            # Step 4 — plan
            request['scaffold_plan'] = self._plan_scaffold(request, config, **kwargs)

            # Step 5 — directory structure (first side effect: from here on a failure
            # can leave a partial scaffold)
            writing_started = True
            root = self.__resolve_output_path(request, config)
            before = self.__snapshot(root)
            self._scaffold_structure(request, config, root, **kwargs)
            result['project_root'] = root

            # Step 6 — build manifest
            manifest_content = self._generate_build_manifest(request, config, **kwargs)
            manifest_path    = self.__write_build_manifest(request, root, manifest_content)
            result['build_manifest_path'] = manifest_path
            result['scaffolded_files'].append(manifest_path)

            # Step 7 — dependency config (optional)
            dep = self._generate_dependency_config(request, config, **kwargs)
            if dep:
                p = self.__write_file(root, self._dependency_file_name(request), dep)
                result['scaffolded_files'].append(p)

            # Step 8 — git config (skipped when git_init is False)
            if request.get('git_init', True):
                for fname, content in self._generate_git_config(request, config, **kwargs).items():
                    result['scaffolded_files'].append(self.__write_file(root, fname, content))

            # Step 9 — env templates
            for fname, content in self._generate_env_templates(request, config, **kwargs).items():
                result['scaffolded_files'].append(self.__write_file(root, fname, content))

            # Step 10 — readme
            readme_path = self.__write_file(
                root, 'README.md',
                self._generate_readme_scaffold(request, config, **kwargs)
            )
            result['readme_path'] = readme_path
            result['scaffolded_files'].append(readme_path)

            # Step 11 — license
            lic = self._generate_license(request, config, **kwargs)
            if lic:
                result['scaffolded_files'].append(self.__write_file(root, 'LICENSE', lic))

            # Step 12 — docker
            if request.get('include_docker', True):
                for fname, content in self._generate_docker_config(
                    request, config, **kwargs
                ).items():
                    result['scaffolded_files'].append(self.__write_file(root, fname, content))

            # Step 13 — makefile
            if request.get('include_makefile', True):
                mk = self._generate_makefile(request, config, **kwargs)
                if mk:
                    result['scaffolded_files'].append(self.__write_file(root, 'Makefile', mk))

            # Step 13b — starter source, tests, CI, dev container (optional hook)
            if request.get('include_starter', True):
                for fname, content in self._generate_starter_files(
                    request, config, **kwargs
                ).items():
                    result['scaffolded_files'].append(self.__write_file(root, fname, content))

            # Record files created outside __write_file (package markers etc. made by
            # _scaffold_structure) so scaffolded_files describes the whole workspace.
            listed = set(result['scaffolded_files'])
            result['scaffolded_files'] += sorted(
                f for f in self.__snapshot(root) - before if f not in listed)

            # Step 14 — validate output
            if not self._validate_output(result, config, **kwargs):
                output_invalid = True
                raise ValueError(f'[{self.bootstrapper_name}] Output validation failed')

            # Step 15 — latency SLO
            latency = (time.time() - start) * 1000
            max_ms  = float(kwargs.get(
                'max_latency_ms',
                config.get('max_latency_ms', os.getenv('BOOTSTRAP_MAX_LATENCY_MS', 10000))
            ))
            result['latency_ms'] = latency
            if latency > max_ms:
                logging.warning(
                    f'[{self.bootstrapper_name}] Latency SLO breach: {latency:.0f}ms > {max_ms:.0f}ms'
                )

            # Step 16 — observability log
            request['scaffolded_files'] = result['scaffolded_files']
            result.update({'scaffold_key': key, 'success': True, 'status': 'scaffolded'})
            logging.info({
                'bootstrapper':  self.bootstrapper_name,
                'scaffold_key':  key,
                'trace_id':      trace_id,
                'latency_ms':    round(latency, 2),
                'files_created': len(result['scaffolded_files']),
                'project_root':  root,
            })

            # A2C handoff
            a2c_cfg = config.get('a2c', {})
            if a2c_cfg.get('enabled', False):
                result['dev_request'] = self.__build_dev_request(request, a2c_cfg, config, root)

            # Settle succeeded. The stored result includes dev_request, so a replay
            # feeds the same hand-off into the A2C phase. A deliberate re-scaffold
            # (idempotency=False) settles retryable instead: the claim is then only
            # mutual exclusion, and the next deliberate run can claim again.
            if self.idempotency:
                guard.succeed(dict(result))
            else:
                guard.fail(retryable=True)
            return result

        except Exception as e:
            # Output validation failure: final (never blindly re-run). Any other failure
            # after Step 5 began: UNKNOWN, parked for reconciliation. Before Step 5:
            # retryable — nothing was written.
            if guard is not None and not guard.settled:
                if output_invalid:
                    guard.fail(retryable=False)
                else:
                    guard.settle_exception(e, side_effects_possible=writing_started)
            return self._handle_error(e, request, result, config, **kwargs)
        finally:
            # Cancellation and any other escape: never leave a claim IN_PROGRESS.
            if guard is not None and not guard.settled:
                guard.settle_exception(RuntimeError('interrupted'),
                                       side_effects_possible=writing_started)

    # ──────────────────────────────────────────────────────────────────────────
    # PROTECTED — override in subclass
    # ──────────────────────────────────────────────────────────────────────────

    @abstractmethod
    def _validate_request(self, request, config=None, **kwargs) -> bool:
        """
        Validate ScaffoldRequest before scaffold begins.
        Required checks:
          - project_name, runtime, platform, build_tool present
          - runtime in APPROVED_RUNTIMES
          - platform in APPROVED_PLATFORMS
          - build_tool in APPROVED_BUILD_TOOLS[runtime]
          - Java: group_id + artifact_id present
          - Python: package_name present
        Return False to abort with ValueError.
        """
        pass

    def _resolve_config(self, request, config=None, **kwargs) -> ScaffoldRequest:
        """
        Load ScaffoldRequest from an external source (default implementation).
          source='json':   scaffold-config.json ['scaffold'] section
          source='prompt': natural-language prompt via config['llm_service']
        Inline fields keep priority over loaded ones (priority 1 = inline).
        The result has source='inline' and resolved_from='json'|'prompt', so a
        request is never resolved twice. Override only to add a source.
        """
        return resolve_scaffold_request(request, config)

    @abstractmethod
    def _plan_scaffold(self, request, config=None, **kwargs) -> List[dict]:
        """
        Build ordered task list for observability + resume-on-failure.
        Returns: [{'step': 1, 'file': 'pyproject.toml', 'description': '...'}, ...]
        """
        pass

    @abstractmethod
    def _scaffold_structure(self, request, config=None, project_root='./', **kwargs) -> None:
        """
        Create directory tree.  Use self.__create_directory(path) per directory.
        Must create ALL directories required by subsequent _generate_* calls.
        """
        pass

    @abstractmethod
    def _generate_build_manifest(self, request, config=None, **kwargs) -> str:
        """
        Generate primary build config file content (NOT the file write — just content).
          Python/Poetry  →  pyproject.toml  (with [tool.poetry.dependencies])
          Python/Pip     →  setup.cfg       (with [options] install_requires)
          Java/Maven     →  pom.xml         (with <dependencies>)
          Java/Gradle    →  build.gradle    (with dependencies { ... })
          Node/npm       →  package.json
          Go             →  go.mod
        Returns file content as string.
        """
        pass

    def _generate_dependency_config(self, request, config=None, **kwargs) -> Optional[str]:
        """
        Generate secondary dependency file (optional — return None if not needed).
          Python/Pip   →  requirements.txt + dev requirements
          Others       →  None (dependencies embedded in build manifest)
        Default: returns None.
        """
        return None

    def _dependency_file_name(self, request) -> str:
        """Filename for the dependency config file.  Default: 'requirements.txt'."""
        return 'requirements.txt'

    @abstractmethod
    def _generate_git_config(self, request, config=None, **kwargs) -> Dict[str, str]:
        """
        Generate git configuration files.
        Returns: {'.gitignore': content, '.gitattributes': content}
        .gitignore MUST exclude:
          Python:  __pycache__/, *.pyc, .venv/, .env, chroma_db/, *.zip, *.egg-info/
          Java:    target/, *.class, .idea/, *.jar, .gradle/
        """
        pass

    @abstractmethod
    def _generate_env_templates(self, request, config=None, **kwargs) -> Dict[str, str]:
        """
        Generate environment configuration templates.
          Python:       {'.env.example': content}
          Spring Boot:  {'src/main/resources/application.yml': content,
                         'src/main/resources/application-dev.yml': content,
                         'src/main/resources/application-prod.yml': content}
        Returns: {relative_path: content}
        """
        pass

    @abstractmethod
    def _generate_readme_scaffold(self, request, config=None, **kwargs) -> str:
        """
        Generate README.md scaffold.
        Must include:
          - Project name + one-line description placeholder
          - Stack badges (runtime, platform, build tool)
          - E2A / A2C framework attribution link
          - Getting Started section (install, run, test commands)
          - Project structure tree (matches _scaffold_structure output)
          - Architecture reference (E2A spike framing if applicable)
          - License section
        Returns README.md content as string.
        """
        pass

    def _generate_license(self, request, config=None, **kwargs) -> Optional[str]:
        """
        Generate LICENSE file content.
        Default: Apache-2.0.  Override to add full license texts.
        Returns None for PROPRIETARY (no LICENSE file created).
        """
        license_type = request.get('license', 'Apache-2.0')
        year = time.strftime('%Y')
        name = request.get('project_name', '')
        if license_type == 'MIT':
            return (
                f'MIT License\n\nCopyright (c) {year} {name}\n\n'
                'Permission is hereby granted, free of charge, to any person obtaining a copy...'
            )
        elif license_type == 'PROPRIETARY':
            return None
        # Default Apache-2.0
        return (
            f'Copyright {year} {name}\n\n'
            'Licensed under the Apache License, Version 2.0 (the "License");\n'
            'you may not use this file except in compliance with the License.\n'
            'You may obtain a copy of the License at\n\n'
            '    http://www.apache.org/licenses/LICENSE-2.0\n'
        )

    @abstractmethod
    def _generate_docker_config(self, request, config=None, **kwargs) -> Dict[str, str]:
        """
        Generate Docker configuration files.
        Returns: {'Dockerfile': content, '.dockerignore': content}
        Dockerfile requirements:
          - Multi-stage build (builder + runtime image)
          - Run as non-root user (UID 1001)
          - Expose correct port (Python: 8000, Java: 8080)
          - HEALTHCHECK instruction pointing to /health
          - COPY only necessary artifacts from builder stage
        """
        pass

    def _generate_makefile(self, request, config=None, **kwargs) -> Optional[str]:
        """
        Generate Makefile with common commands.
        Default: returns None.  Override per runtime.
        Standard targets: install, test, lint, build, run, docker-build, clean
        """
        return None

    def _generate_starter_files(self, request, config=None, **kwargs) -> Dict[str, str]:
        """
        Starter files that make the scaffold runnable on day zero: the
        application entry point, a first test, the CI workflow, a dev
        container and a compose file. Returns {relative_path: content}.
        Default: none. Override per runtime. Skipped when
        request['include_starter'] is False.
        """
        return {}

    def _validate_output(self, result, config=None, **kwargs) -> bool:
        """
        Confirm required files were created.
        Default: checks build_manifest_path + readme_path in scaffolded_files.
        Override to add runtime-specific validation.
        """
        required = [result.get('build_manifest_path'), result.get('readme_path')]
        return all(f and f in result.get('scaffolded_files', []) for f in required)

    def _handle_error(self, error, request, result, config=None, **kwargs) -> ScaffoldResult:
        """
        Error handler.  Default: log + return result with success=False.
        Override to add alerting, partial-state cleanup, or recovery logic.
        """
        logging.error(
            f'[{self.bootstrapper_name}][{request.get("project_name","?")}] {error}'
        )
        result.setdefault('errors', []).append(str(error))
        result['success'] = False
        return result

    # ──────────────────────────────────────────────────────────────────────────
    # PRIVATE — framework internals.  Never override.
    # ──────────────────────────────────────────────────────────────────────────

    def __load_json_config(self, config_path: str) -> ScaffoldRequest:
        """Load ScaffoldRequest from scaffold-config.json['scaffold'] key."""
        return _load_json_scaffold(config_path)

    def __load_prompt_config(self, prompt: str, config: dict) -> ScaffoldRequest:
        """Parse a ScaffoldRequest from a prompt through config['llm_service']."""
        return _load_prompt_scaffold(prompt, config)

    def __write_file(self, project_root: str, relative_path: str, content: str) -> str:
        """Write content to file.  Creates parent dirs.  Returns absolute path."""
        full = Path(project_root) / relative_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding='utf-8')
        return str(full.resolve())

    def __create_directory(self, path: str) -> None:
        """mkdir -p.  Idempotent."""
        Path(path).mkdir(parents=True, exist_ok=True)

    def __generate_scaffold_key(self, request: ScaffoldRequest) -> str:
        """
        Business-level idempotency key.
        Format: {project_name}:{runtime}:{build_tool}:{platform}
        Same key = project already scaffolded (skip when idempotency=True).
        """
        return (
            f"{request.get('project_name','unknown')}"
            f":{request.get('runtime','unknown')}"
            f":{request.get('build_tool','unknown')}"
            f":{request.get('platform','standalone')}"
        )

    def __not_owner(self, claim, key: str, result: ScaffoldResult) -> ScaffoldResult:
        """Typed outcome for a caller that does not own the scaffold_key."""
        st = status_of(claim)
        if st == 'REPLAY':
            stored = dict(claim.result or {})
            root = stored.get('project_root')
            if root and not (Path(root).is_dir() and any(Path(root).iterdir())):
                # The settled workspace was removed (e.g. by a saga). Replaying
                # its path would hand callers a project that does not exist.
                result.update({'success': False, 'scaffold_key': key, 'status': 'recovery_required'})
                result['errors'].append(f'replayed scaffold is missing at {root}; reconcile the '
                                        'claim before re-scaffolding')
                return result
            stored.update(status='replay', replayed=True)
            return stored          # nothing is written
        why = {
            'IN_PROGRESS': 'another run holds this scaffold_key',
            'CONFLICT': 'same scaffold_key presented with a different request',
            'RECOVERY_REQUIRED': 'a previous owner expired without settling; a partial '
                                 'scaffold may exist — reconcile before re-running',
            'FAILED_FINAL': 'this scaffold_key failed finally and is not re-executed',
        }.get(st, st)
        result.update({'success': False, 'scaffold_key': key, 'status': st.lower()})
        result['errors'].append(why)
        return result

    def __output_base(self, request: ScaffoldRequest, config: dict) -> str:
        """request['output_path'] > config['output_path'] > env BOOTSTRAP_OUTPUT_PATH > './'.
        Single resolution rule shared by the idempotency check and Step 5."""
        return (request.get('output_path') or config.get('output_path')
                or os.getenv('BOOTSTRAP_OUTPUT_PATH', './'))

    def __project_dir(self, request: ScaffoldRequest, config: dict) -> Path:
        return Path(self.__output_base(request, config)) / request.get('project_name', 'project')

    def __is_already_scaffolded(self, request: ScaffoldRequest, config: dict) -> bool:
        """
        Fast-path check: the project directory that Step 5 would use exists and is
        non-empty. Under concurrent callers the atomic claim (Step 3) is the
        authority; this check is consulted only after the claim is won.
        """
        d = self.__project_dir(request, config)
        return d.exists() and any(d.iterdir())

    @staticmethod
    def __snapshot(root: str) -> set:
        """Absolute paths of all files under root (empty if root is missing)."""
        r = Path(root)
        return {str(p.resolve()) for p in r.rglob('*') if p.is_file()} if r.exists() else set()

    def __resolve_output_path(self, request: ScaffoldRequest, config: dict) -> str:
        """
        Resolve project root.
        Order: request['output_path'] > config['output_path'] >
               env BOOTSTRAP_OUTPUT_PATH > './'
        """
        root = str(self.__project_dir(request, config).resolve())
        Path(root).mkdir(parents=True, exist_ok=True)
        return root

    def __write_build_manifest(self, request, project_root: str, content: str) -> str:
        """Write build manifest to runtime-appropriate filename."""
        key      = (request.get('runtime','python'), request.get('build_tool','poetry'))
        filename = self.MANIFEST_FILENAMES.get(key, 'build.config')
        return self.__write_file(project_root, filename, content)

    def __build_dev_request(self, request: ScaffoldRequest, a2c_cfg: dict,
                            config: dict = None, project_root: str = None) -> dict:
        """
        Build A2C DevRequest from ScaffoldRequest + config['a2c'] section.
        Populates project_name, language, target_cloud, tenant_id and
        project_root automatically, so A2C's SDLCWorkflow can claim the request
        per tenant and write its artifacts into this workspace.
        Called at Step 16 (and on the idempotent skip) when config['a2c']['enabled'].
        """
        config = config or {}
        dev = {
            'project_name':   request.get('project_name'),
            'project_type':   a2c_cfg.get('project_type') or request.get('project_type', ''),
            'mandatory_nfrs': list(a2c_cfg.get('mandatory_nfrs', [])),
            'target_cloud':   request.get('platform', a2c_cfg.get('target_cloud', 'aws')),
            'language':       request.get('runtime', 'python'),
            'context':        a2c_cfg.get('context', ''),
            # v1.1.2: one port for Dockerfile and Terraform; the package for the Lambda handler
            'port':           int(request.get('port', 8080 if request.get('runtime') == 'java' else 8000)),
            'package_name':   request.get('package_name'),
            # v1.2 (A-3): app settings, for Terraform
            'settings':       list(request.get('settings') or a2c_cfg.get('settings') or []),
        }
        tenant = request.get('tenant_id') or config.get('tenant_id')
        if tenant:
            dev['tenant_id'] = tenant
        if project_root:
            dev['project_root'] = project_root
        return dev


MAVEN_COORD = re.compile(r'^([\w.\-]+):([\w.\-]+)(?::([\w.\-]+))?(?:@(compile|runtime|test|provided))?$')


def maven_dependency(spec: str) -> str:
    """A Spring starter short name ('web' -> spring-boot-starter-web) or, v1.2 (P-5), a Maven
    coordinate 'group:artifact[:version][@scope]'; without a version, the Spring Boot BOM decides."""
    if ':' not in spec:
        return ('        <dependency>\n            <groupId>org.springframework.boot</groupId>\n'
                f'            <artifactId>spring-boot-starter-{spec}</artifactId>\n        </dependency>')
    m = MAVEN_COORD.match(spec.strip())
    if not m:
        raise ValueError(f"dependency {spec!r}: use 'group:artifact[:version][@scope]'")
    group, artifact, version, scope = m.groups()
    return ('        <dependency>\n'
            f'            <groupId>{group}</groupId>\n            <artifactId>{artifact}</artifactId>\n'
            + (f'            <version>{version}</version>\n' if version else '')
            + (f'            <scope>{scope}</scope>\n' if scope and scope != 'compile' else '')
            + '        </dependency>')


_REQ = re.compile(r'^\s*([A-Za-z0-9_.\-]+)\s*(?:\[([^\]]*)\])?\s*(.*)$')


def _dependency_name(spec: str) -> str:
    m = _REQ.match(spec)
    return (m.group(1) if m else spec).lower()


def _with_defaults(specs: List[str], defaults: List[str]) -> List[str]:
    """Add each default dependency the request does not already name."""
    names = {_dependency_name(d) for d in specs}
    return list(specs) + [d for d in defaults if _dependency_name(d) not in names]


def _poetry_dependency(spec: str) -> str:
    """One PEP 508 requirement as a Poetry TOML line. Keeps version
    constraints and extras; 'name @ git+URL@ref' becomes a git source."""
    if ' @ ' in spec:
        name, url = (x.strip() for x in spec.split(' @ ', 1))
        url = url[len('git+'):] if url.startswith('git+') else url
        ref = None
        if '@' in url.rsplit('/', 1)[-1]:
            url, ref = url.rsplit('@', 1)
        ref_part = f', tag = "{ref}"' if ref else ''
        return f'"{name}" = {{ git = "{url}"{ref_part} }}'
    m = _REQ.match(spec)
    if not m:
        return f'"{spec.strip()}" = "*"'
    name, extras, constraint = m.group(1), m.group(2), (m.group(3) or '').strip() or '*'
    if extras:
        items = ', '.join(f'"{e.strip()}"' for e in extras.split(',') if e.strip())
        return f'"{name}" = {{ version = "{constraint}", extras = [{items}] }}'
    return f'"{name}" = "{constraint}"'


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  Concrete Implementation — PythonPoetryBootstrapper                     ║
# ╚══════════════════════════════════════════════════════════════════════════╝

class PythonPoetryBootstrapper(BaseProjectBootstrapper):
    """
    Bootstrapper for Python + Poetry projects.
    Supports: fastapi_microservice, lambda, langgraph_agent, library.
    """
    bootstrapper_name = 'PythonPoetryBootstrapper'

    def _validate_request(self, request, config=None, **kwargs) -> bool:
        required = ['project_name', 'runtime', 'platform', 'build_tool', 'package_name']
        if not all(k in request for k in required):
            logging.error(f'[{self.bootstrapper_name}] Missing fields: '
                          f'{[k for k in required if k not in request]}')
            return False
        if request['runtime'] != 'python' or request['build_tool'] != 'poetry':
            logging.error(f'[{self.bootstrapper_name}] Wrong runtime/build_tool')
            return False
        if request['platform'] not in self.APPROVED_PLATFORMS:
            logging.error(f'[{self.bootstrapper_name}] Platform not approved: {request["platform"]}')
            return False
        if 'project_type' not in request:
            logging.info(f'[{self.bootstrapper_name}] project_type not given — '
                         'using fastapi_microservice')
        return True

    def _plan_scaffold(self, request, config=None, **kwargs) -> List[dict]:
        return [
            {'step': 1,  'file': 'pyproject.toml',      'description': 'Poetry build manifest'},
            {'step': 2,  'file': '.gitignore',           'description': 'Python git ignore rules'},
            {'step': 3,  'file': '.env.example',         'description': 'Environment variable template'},
            {'step': 4,  'file': 'README.md',            'description': 'Project README scaffold'},
            {'step': 5,  'file': 'LICENSE',              'description': 'Apache-2.0 license'},
            {'step': 6,  'file': 'Dockerfile',           'description': 'Multi-stage Python Docker build'},
            {'step': 7,  'file': '.dockerignore',        'description': 'Docker ignore rules'},
            {'step': 8,  'file': 'Makefile',             'description': 'Common dev commands'},
            {'step': 9,  'file': 'src/__init__.py',      'description': 'Package root'},
            {'step': 10, 'file': 'tests/conftest.py',    'description': 'Pytest configuration'},
        ]

    def _scaffold_structure(self, request, config=None, project_root='./', **kwargs) -> None:
        pkg = request.get('package_name', request['project_name'].lower())
        ptype = request.get('project_type', 'fastapi_microservice')
        dirs = [
            f'{project_root}/src/{pkg}',
            f'{project_root}/src/{pkg}/models',
            f'{project_root}/src/{pkg}/services',
            f'{project_root}/src/{pkg}/routers',
            f'{project_root}/src/{pkg}/tools',
            f'{project_root}/src/{pkg}/config',
            f'{project_root}/tests',
            f'{project_root}/.github/workflows',
        ]
        if ptype == 'langgraph_agent':
            dirs += [
                f'{project_root}/src/{pkg}/agents',
                f'{project_root}/src/{pkg}/rag',
                f'{project_root}/src/{pkg}/workflows',
            ]
        for d in dirs:
            Path(d).mkdir(parents=True, exist_ok=True)
            init = Path(d) / '__init__.py'
            if 'src' in d and not init.exists():
                init.write_text('', encoding='utf-8')

    def _generate_build_manifest(self, request, config=None, **kwargs) -> str:
        name    = request.get('project_name', 'project').lower().replace(' ', '-')
        pkg     = request.get('package_name', name.replace('-', '_'))
        version = request.get('runtime_version', '3.12')
        deps    = request.get('dependencies', [])
        dev     = request.get('dev_dependencies', [])
        if request.get('project_type', 'fastapi_microservice') == 'fastapi_microservice':
            defaults = ['fastapi>=0.111', 'uvicorn[standard]>=0.30']
            if request.get('platform') == 'aws':
                defaults.append('mangum>=0.17')            # Lambda adapter for lambda_entry.py
            deps = _with_defaults(deps, defaults)
            dev = _with_defaults(dev, ['pytest>=8.2', 'httpx>=0.27'])
        deps_toml = '\n'.join(_poetry_dependency(d) for d in deps)
        dev_toml  = '\n'.join(_poetry_dependency(d) for d in dev)
        authors   = ', '.join(json.dumps(a) for a in request.get('authors', []))   # v1.1.2: from the request
        return f'''[tool.poetry]
name = "{name}"
version = "0.1.0"
description = ""
authors = [{authors}]
readme = "README.md"
packages = [{{include = "{pkg}", from = "src"}}]

[tool.poetry.dependencies]
python = ">={version}"
{deps_toml}

[tool.poetry.group.dev.dependencies]
{dev_toml}

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"

[tool.ruff]
line-length = 100
target-version = "py{version.replace('.', '')}"

[tool.mypy]
python_version = "{version}"
strict = true
'''

    def _generate_git_config(self, request, config=None, **kwargs) -> Dict[str, str]:
        return {
            '.gitignore': '''# Python
__pycache__/
*.py[cod]
*.so
.Python
.venv/
venv/
ENV/
*.egg-info/
dist/
build/
.eggs/

# Environment & secrets
.env
.env.*
!.env.example

# Local vector stores & caches
chroma_db/
*.db

# IDE
.idea/
.vscode/
*.DS_Store

# Test artifacts
.pytest_cache/
.coverage
htmlcov/

# Build artifacts
*.zip
*.tar.gz
*.whl
''',
            '.gitattributes': '* text=auto\n*.py text eol=lf\n'
        }

    def _generate_env_templates(self, request, config=None, **kwargs) -> Dict[str, str]:
        platform = request.get('platform', 'aws')
        cloud_vars = {
            'aws':        'AWS_REGION=ap-south-1\nAWS_ACCOUNT_ID=\nBEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0\n',
            'gcp':        'GCP_PROJECT_ID=\nGCP_REGION=us-central1\nVERTEX_MODEL_ID=gemini-2.5-pro\n',
            'azure':      'AZURE_OPENAI_ENDPOINT=\nAZURE_OPENAI_API_KEY=\nAZURE_OPENAI_MODEL=gpt-4o\n',
            'standalone': 'LLM_ENDPOINT=http://localhost:11434\nLLM_MODEL_ID=llama3\n',
        }
        return {
            '.env.example': f'''# Application
APP_NAME={request.get("project_name", "app")}
APP_ENV=development
APP_PORT=8000
LOG_LEVEL=INFO

# Cloud Platform ({platform})
{cloud_vars.get(platform, "")}
# Observability
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
OTEL_SERVICE_NAME={request.get("project_name", "app").lower()}

# E2A Framework NFRs
MIN_CONFIDENCE=0.85
MAX_LATENCY=2.0
MAX_TOKENS=5000
TOOL_TIMEOUT=5.0
TOOL_RETRIES=3
''' + env_example(normalize_settings(request.get('settings')))
        }

    def _generate_readme_scaffold(self, request, config=None, **kwargs) -> str:
        name     = request.get('project_name', 'Project')
        pkg      = request.get('package_name', name.lower())
        platform = request.get('platform', 'aws').upper()
        ptype    = request.get('project_type', 'fastapi_microservice')
        return f'''# {name}

> **E2A Architectural Spike** — {ptype.replace("_", " ").title()}

<!-- One-line description placeholder -->

Built on the [E2A Architecture Framework](https://github.com/subhamviky/e2a-framework) |
Generated by [A2C Framework](https://github.com/subhamviky/a2c-framework)

---

## Stack

![Python](https://img.shields.io/badge/Python-{request.get("runtime_version","3.12")}-blue?logo=python)
![Platform](<https://img.shields.io/badge/Platform-{platform}-orange>)
![Poetry](https://img.shields.io/badge/Build-Poetry-60A5FA)

---

## Getting Started

```bash
# Install dependencies
poetry install

# Copy environment variables
cp .env.example .env

# Run locally
make run

# Run tests
make test
```

## Project Structure

```
{name}/
├── src/
│   └── {pkg}/
│       ├── models/      # Domain entities (E2A: AgentState / TypedDict)
│       ├── services/    # Business logic  (E2A: BIMP / @Service)
│       ├── routers/     # API exposure    (E2A: OData Binding / @RestController)
│       └── tools/       # MCP tools       (E2A: BaseToolService)
├── tests/
├── pyproject.toml
├── Dockerfile
└── Makefile
```

## Architecture

Follows E2A Clean Architecture layers:
- **Data model:** Pydantic BaseModel (equivalent: CDS View Entity / JPA @Entity)
- **Interface contract:** Abstract base classes (equivalent: BDEF / Java Interface)
- **Business logic:** Service classes (equivalent: BIMP / @Service)
- **Exposure layer:** FastAPI APIRouter (equivalent: OData Service Binding / @RestController)

## License

Apache License 2.0 — see [LICENSE](LICENSE)
'''

    def _generate_docker_config(self, request, config=None, **kwargs) -> Dict[str, str]:
        pkg     = request.get('package_name', 'app')
        version = request.get('runtime_version', '3.12')
        port    = int(request.get('port', 8000))
        extra   = ''.join(f'COPY {p.strip("/")}/ /app/{p.strip("/")}/\n'
                          for p in request.get('include_paths', []))          # v1.1.2: data folders
        return {
            'Dockerfile': f'''# Multi-stage Python build — non-root runtime image
FROM python:{version}-slim AS builder
# Build where the runtime runs: the venv's scripts hard-code their interpreter path
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git \\
    && rm -rf /var/lib/apt/lists/* && pip install "poetry>=2.0,<3"
COPY pyproject.toml poetry.lock* ./
RUN poetry config virtualenvs.in-project true \\
    && poetry install --only main --no-root --no-interaction

FROM python:{version}-slim AS runtime
WORKDIR /app
RUN groupadd -r appgroup && useradd -r -g appgroup -u 1001 appuser
COPY --from=builder /app/.venv /app/.venv
COPY src/ /app/src/
{extra}ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH="/app/src"
USER appuser
EXPOSE {port}
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \\
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:{port}/health')" || exit 1
CMD ["uvicorn", "{pkg}.main:app", "--host", "0.0.0.0", "--port", "{port}"]
''',
            '.dockerignore': '.venv\n__pycache__\n*.pyc\n.env\n.git\ntests\n*.md\n'
        }

    def _generate_starter_files(self, request, config=None, **kwargs) -> Dict[str, str]:
        pkg = request.get('package_name', 'app')
        name = request.get('project_name', 'App')
        version = request.get('runtime_version', '3.12')
        files: Dict[str, str] = {}
        if request.get('project_type', 'fastapi_microservice') == 'fastapi_microservice':
            files[f'src/{pkg}/main.py'] = (
                f'"""{name} - FastAPI entry point (scaffolded by P0)."""\n'
                'import logging\n\n'
                'from fastapi import FastAPI\n\n'
                f'logger = logging.getLogger("{pkg}")\n\n'
                f'app = FastAPI(title="{name}")\n\n\n'
                '@app.get("/health")\n'
                'def health() -> dict[str, str]:\n'
                '    """Liveness probe used by the container HEALTHCHECK and the platform."""\n'
                f'    return {{"status": "UP", "service": "{name}"}}\n')
            if request.get('platform') == 'aws':
                files[f'src/{pkg}/lambda_entry.py'] = (
                    '"""AWS Lambda entry point (scaffolded by P0): API Gateway -> FastAPI through Mangum.\n'
                    'infra/main.tf points var.lambda_handler at this module\'s handler."""\n'
                    'from mangum import Mangum\n\n'
                    'from .main import app\n\n'
                    'handler = Mangum(app, lifespan="off")\n')
            files['tests/test_health.py'] = (
                'from fastapi.testclient import TestClient\n\n'
                f'from {pkg}.main import app\n\n\n'
                'def test_health_reports_up() -> None:\n'
                '    response = TestClient(app).get("/health")\n'
                '    assert response.status_code == 200\n'
                '    assert response.json()["status"] == "UP"\n')
        files['.github/workflows/ci.yml'] = (
            'name: ci\n\non:\n  push:\n    branches: [main]\n  pull_request:\n\n'
            'permissions:\n  contents: read\n\n'
            'jobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n'
            '      - uses: actions/checkout@v6\n'
            '      - uses: actions/setup-python@v6\n'
            f'        with:\n          python-version: "{version}"\n'
            '      - run: pipx install "poetry>=2.0,<3"\n'
            '      - run: poetry install --no-interaction\n'
            '      - run: poetry run pytest -q\n')
        evaluation = normalize_evaluation(request.get('evaluation'))
        if request.get('release_gate') or evaluation:   # v1.2.1 (C-04): E2A's release gate in the CI
            files['.github/workflows/ci.yml'] += ci_step(pkg, evaluation)
        if evaluation:                                  # v1.2.1 (C-04, D-2): the declared evaluation sets
            files[f'src/{pkg}/release/__init__.py'] = '"""The release gate (generated by A2C)."""\n'
            files[f'src/{pkg}/release/gate.py'] = gate_module(pkg, evaluation)
            files[evaluation['set']] = example_set()
            if evaluation.get('redteam'):
                files[evaluation['redteam']] = example_redteam()
        files['.devcontainer/devcontainer.json'] = json.dumps({
            'name': name,
            'image': f'mcr.microsoft.com/devcontainers/python:1-{version}',
            'postCreateCommand': 'pipx install "poetry>=2.0,<3" && poetry install',
            'forwardPorts': [int(request.get('port', 8000))],
            'customizations': {'vscode': {'extensions': [
                'ms-python.python', 'charliermarsh.ruff', 'hashicorp.terraform']}},
        }, indent=2) + '\n'
        files['docker-compose.yml'] = (
            f'services:\n  app:\n    build: .\n    ports:\n      - "{int(request.get("port", 8000))}:{int(request.get("port", 8000))}"\n'
            '    env_file:\n      - path: .env\n        required: false\n')
        settings = normalize_settings(request.get('settings'))
        if settings:                    # v1.2 (A-3): the declared app settings and their test
            files[f'src/{pkg}/settings.py'] = python_module(settings)
            files['tests/test_settings.py'] = python_test(pkg, settings)
        contracts = [Contract(c['path'], c['schema']) for c in request.get('contract_schemas') or []]
        if contracts:                   # v1.2 (A-5): models from the declared contracts, and their test
            files[f'src/{pkg}/contracts/__init__.py'] = '"""Models generated by A2C from the contracts."""\n'
            for c in contracts:
                files[f'src/{pkg}/contracts/{module_name(c.path)}.py'] = contract_python(c)
            files['tests/test_contracts.py'] = contract_python_test(pkg, contracts)
        return files

    def _generate_makefile(self, request, config=None, **kwargs) -> str:
        pkg = request.get('package_name', 'app')
        return f'''.PHONY: install test lint build run docker-build clean

install:
\tpoetry install

test:
\tpoetry run pytest tests/ -v --cov=src --cov-report=term-missing

lint:
\tpoetry run ruff check src/ tests/
\tpoetry run mypy src/

build:
\tpoetry build

run:
\tpoetry run uvicorn {pkg}.main:app --reload --host 0.0.0.0 --port 8000

docker-build:
\tdocker build -t {pkg}:local .

clean:
\tfind . -type d -name __pycache__ -exec rm -rf {{}} +
\trm -rf dist/ .coverage htmlcov/ .mypy_cache/
'''


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  Concrete Implementation — JavaMavenBootstrapper                        ║
# ╚══════════════════════════════════════════════════════════════════════════╝

class JavaMavenBootstrapper(BaseProjectBootstrapper):
    """
    Bootstrapper for Java + Maven (Spring Boot) projects.
    Supports: spring_boot, library.
    """
    bootstrapper_name = 'JavaMavenBootstrapper'

    def _validate_request(self, request, config=None, **kwargs) -> bool:
        required = ['project_name', 'runtime', 'platform', 'build_tool',
                    'group_id', 'artifact_id', 'project_type']
        if not all(k in request for k in required):
            logging.error(f'[{self.bootstrapper_name}] Missing: '
                          f'{[k for k in required if k not in request]}')
            return False
        if request['runtime'] != 'java' or request['build_tool'] != 'maven':
            logging.error(f'[{self.bootstrapper_name}] Wrong runtime/build_tool')
            return False
        if request['platform'] not in self.APPROVED_PLATFORMS:
            logging.error(f'[{self.bootstrapper_name}] Platform not approved: {request["platform"]}')
            return False
        return True

    def _plan_scaffold(self, request, config=None, **kwargs) -> List[dict]:
        return [
            {'step': 1, 'file': 'pom.xml',                          'description': 'Maven build manifest'},
            {'step': 2, 'file': 'src/main/resources/application.yml','description': 'Spring Boot config'},
            {'step': 3, 'file': '.gitignore',                        'description': 'Java git ignore'},
            {'step': 4, 'file': 'README.md',                         'description': 'README scaffold'},
            {'step': 5, 'file': 'Dockerfile',                        'description': 'Multi-stage Java build'},
            {'step': 6, 'file': 'Makefile',                          'description': 'Common Maven commands'},
        ]

    def _scaffold_structure(self, request, config=None, project_root='./', **kwargs) -> None:
        gid  = request.get('group_id', 'com.example')
        name = request.get('project_name', 'App')
        gid_path = gid.replace('.', '/')
        for d in [
            f'{project_root}/src/main/java/{gid_path}/config',
            f'{project_root}/src/main/java/{gid_path}/domain',
            f'{project_root}/src/main/java/{gid_path}/service',
            f'{project_root}/src/main/java/{gid_path}/controller',
            f'{project_root}/src/main/java/{gid_path}/repository',
            f'{project_root}/src/main/resources',
            f'{project_root}/src/test/java/{gid_path}',
            f'{project_root}/.github/workflows',
        ]:
            Path(d).mkdir(parents=True, exist_ok=True)

    def _generate_build_manifest(self, request, config=None, **kwargs) -> str:
        gid     = request.get('group_id', 'com.example')
        aid     = request.get('artifact_id', 'app')
        name    = request.get('project_name', 'App')
        sb_ver  = request.get('spring_boot_version', '3.3.0')
        java_v  = request.get('java_source_version', '21')
        deps    = request.get('dependencies', [])
        dep_xml = '\n'.join(maven_dependency(d) for d in deps)       # v1.2 (P-5): starters or coordinates
        return f'''<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0
         https://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>

    <parent>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-parent</artifactId>
        <version>{sb_ver}</version>
        <relativePath/>
    </parent>

    <groupId>{gid}</groupId>
    <artifactId>{aid}</artifactId>
    <version>0.1.0-SNAPSHOT</version>
    <name>{name}</name>
    <description>E2A Java Reference Spike — {name}</description>

    <properties>
        <java.version>{java_v}</java.version>
        <maven.compiler.source>{java_v}</maven.compiler.source>
        <maven.compiler.target>{java_v}</maven.compiler.target>
    </properties>

    <dependencies>
{dep_xml}
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-test</artifactId>
            <scope>test</scope>
        </dependency>
    </dependencies>

    <build>
        <plugins>
            <plugin>
                <groupId>org.springframework.boot</groupId>
                <artifactId>spring-boot-maven-plugin</artifactId>
            </plugin>
        </plugins>
    </build>
</project>
'''

    def _generate_git_config(self, request, config=None, **kwargs) -> Dict[str, str]:
        return {
            '.gitignore': '''# Maven
target/
*.class
*.jar
*.war

# IDE
.idea/
.vscode/
*.iml
.classpath
.project
.settings/

# Environment
.env
.env.*
!.env.example

# OS
.DS_Store
Thumbs.db
''',
        }

    def _generate_env_templates(self, request, config=None, **kwargs) -> Dict[str, str]:
        name = request.get('project_name', 'app').lower()
        return {
            'src/main/resources/application.yml': f'''spring:
  application:
    name: {name}

server:
  port: 8080

management:
  endpoints:
    web:
      exposure:
        include: health,info,prometheus
  endpoint:
    health:
      show-details: always

logging:
  pattern:
    console: '%d{{yyyy-MM-dd HH:mm:ss}} - %msg%n'
''' + java_yaml(normalize_settings(request.get('settings'))),
            'src/main/resources/application-dev.yml': 'spring:\n  jpa:\n    show-sql: true\n',
            'src/main/resources/application-prod.yml': 'logging:\n  level:\n    root: WARN\n',
        }

    def _generate_readme_scaffold(self, request, config=None, **kwargs) -> str:
        name = request.get('project_name', 'Project')
        gid  = request.get('group_id', 'com.example')
        aid  = request.get('artifact_id', 'app')
        jv   = request.get('java_source_version', '21')
        sb   = request.get('spring_boot_version', '3.3.0')
        return f'''# {name}

> **E2A Java Reference Spike** — Spring Boot Microservice

Built on the [E2A Architecture Framework](https://github.com/subhamviky/e2a-framework)

---

## Stack

![Java](https://img.shields.io/badge/Java-{jv}-ED8B00?logo=openjdk)
![Spring Boot](https://img.shields.io/badge/Spring_Boot-{sb}-6DB33F?logo=spring)

---

## Getting Started

```bash
# Build
mvn clean package

# Run
mvn spring-boot:run

# Test
mvn test
```

## Project Structure

```
{name}/
├── src/main/java/{gid.replace(".", "/")}/
│   ├── config/      # Spring configuration
│   ├── domain/      # Domain entities (E2A: CDS View Entity / JPA @Entity)
│   ├── service/     # Business logic  (E2A: BIMP / @Service)
│   ├── controller/  # REST controllers (E2A: OData Binding / @RestController)
│   └── repository/  # Data access
├── src/main/resources/
│   └── application.yml
├── pom.xml
└── Dockerfile
```

## License

Apache License 2.0 — see [LICENSE](LICENSE)
'''

    def _generate_docker_config(self, request, config=None, **kwargs) -> Dict[str, str]:
        name = request.get('artifact_id', 'app')
        jv   = request.get('java_source_version', '21')
        port = int(request.get('port', 8080))
        e2a = request.get('e2a_java')      # D-01: e2a-java, built from E2A's tag (no package registry)
        build = (f'''RUN apk add --no-cache maven git \\
 && git clone -q --depth 1 --branch v{e2a} https://github.com/subhamviky/e2a-framework.git /e2a \\
 && mvn -B -q -f /e2a/java/pom.xml install -DskipTests
COPY pom.xml .
COPY src ./src
RUN mvn clean package -DskipTests''' if e2a else '''COPY pom.xml .
COPY src ./src
RUN apk add --no-cache maven && mvn clean package -DskipTests''')
        return {
            'Dockerfile': f'''# Multi-stage Java build — non-root runtime image
FROM eclipse-temurin:{jv}-jdk-alpine AS builder
WORKDIR /build
{build}

FROM eclipse-temurin:{jv}-jre-alpine AS runtime
WORKDIR /app
RUN addgroup -S appgroup && adduser -S appuser -G appgroup -u 1001
COPY --from=builder /build/target/*.jar app.jar
ENV SERVER_PORT={port}
USER appuser
EXPOSE {port}
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \\
  CMD wget -q -O- http://localhost:{port}/actuator/health || exit 1
ENTRYPOINT ["java", "-jar", "app.jar"]
''',
            '.dockerignore': 'target/\n.git\n*.md\n.idea/\n*.iml\n'
        }

    def _generate_starter_files(self, request, config=None, **kwargs) -> Dict[str, str]:
        gid = request.get('group_id', 'com.example')
        name = request.get('project_name', 'App')
        jv = request.get('java_source_version', '21')
        path = gid.replace('.', '/')
        files = {
            f'src/main/java/{path}/Application.java': (
                f'package {gid};\n\n'
                'import org.springframework.boot.SpringApplication;\n'
                'import org.springframework.boot.autoconfigure.SpringBootApplication;\n\n'
                f'/** {name} - Spring Boot entry point (scaffolded by P0). */\n'
                '@SpringBootApplication\n'
                'public class Application {\n\n'
                '    public static void main(String[] args) {\n'
                '        SpringApplication.run(Application.class, args);\n'
                '    }\n}\n'),
            f'src/test/java/{path}/ApplicationTests.java': (
                f'package {gid};\n\n'
                'import static org.assertj.core.api.Assertions.assertThat;\n\n'
                'import org.junit.jupiter.api.Test;\n'
                'import org.springframework.beans.factory.annotation.Autowired;\n'
                'import org.springframework.boot.test.context.SpringBootTest;\n'
                'import org.springframework.context.ApplicationContext;\n\n'
                '@SpringBootTest\n'
                'class ApplicationTests {\n\n'
                '    @Autowired\n'
                '    private ApplicationContext context;\n\n'
                '    @Test\n'
                '    void contextLoads() {\n'
                '        assertThat(context).isNotNull();\n'
                '    }\n}\n'),
            '.github/workflows/ci.yml': (
                'name: ci\n\non:\n  push:\n    branches: [main]\n  pull_request:\n\n'
                'permissions:\n  contents: read\n\n'
                'jobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n'
                '      - uses: actions/checkout@v6\n'
                '      - uses: actions/setup-java@v5\n'
                '        with:\n          distribution: temurin\n'
                f'          java-version: "{jv}"\n          cache: maven\n'
                + (f'      - name: Install e2a-java {request["e2a_java"]} (built from E2A\'s tag; no package registry)\n'
                   f'        run: |\n'
                   f'          git clone -q --depth 1 --branch v{request["e2a_java"]} '
                   f'https://github.com/subhamviky/e2a-framework.git "$RUNNER_TEMP/e2a"\n'
                   f'          mvn -B -q -f "$RUNNER_TEMP/e2a/java/pom.xml" install -DskipTests\n'
                   if request.get('e2a_java') else '')
                + '      - run: mvn -B verify\n'),
            '.devcontainer/devcontainer.json': json.dumps({
                'name': name,
                'image': f'mcr.microsoft.com/devcontainers/java:1-{jv}',
                'features': {'ghcr.io/devcontainers/features/java:1': {
                    'version': 'none', 'installMaven': 'true'}},
                'postCreateCommand': 'mvn -B -q dependency:go-offline',
                'forwardPorts': [8080],
                'customizations': {'vscode': {'extensions': [
                    'vscjava.vscode-java-pack', 'vmware.vscode-boot-dev-pack',
                    'hashicorp.terraform']}},
            }, indent=2) + '\n',
            'docker-compose.yml': 'services:\n  app:\n    build: .\n    ports:\n      - "8080:8080"\n',
        }
        if 'actuator' in request.get('dependencies', []):
            files[f'src/test/java/{path}/HealthEndpointTests.java'] = (
                f'package {gid};\n\n'
                'import static org.assertj.core.api.Assertions.assertThat;\n\n'
                'import org.junit.jupiter.api.Test;\n'
                'import org.springframework.beans.factory.annotation.Autowired;\n'
                'import org.springframework.boot.test.context.SpringBootTest;\n'
                'import org.springframework.boot.test.web.client.TestRestTemplate;\n\n'
                '@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)\n'
                'class HealthEndpointTests {\n\n'
                '    @Autowired\n'
                '    private TestRestTemplate rest;\n\n'
                '    @Test\n'
                '    void healthIsUp() {\n'
                '        String body = rest.getForObject("/actuator/health", String.class);\n'
                '        assertThat(body).contains("UP");\n'
                '    }\n}\n')
        for c in request.get('contract_schemas') or []:         # v1.2 (A-5): records from the contracts
            for fname, src in contract_java(Contract(c['path'], c['schema']), f'{gid}.contracts').items():
                files[f'src/main/java/{path}/contracts/{fname}'] = src
        return files

    def _generate_makefile(self, request, config=None, **kwargs) -> str:
        return '''.PHONY: install build test run docker-build clean

build:
\tmvn clean package -DskipTests

test:
\tmvn test

run:
\tmvn spring-boot:run

docker-build:
\tdocker build -t app:local .

clean:
\tmvn clean
'''


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  Factory — resolves correct bootstrapper from ScaffoldRequest           ║
# ╚══════════════════════════════════════════════════════════════════════════╝

class ProjectBootstrapperFactory:
    """
    Resolves the correct BaseProjectBootstrapper subclass from a ScaffoldRequest.
    Follows the same approved-list governance pattern as E2A agent routing.

    Usage:
        bootstrapper = ProjectBootstrapperFactory.create(request, config)
        result = bootstrapper.bootstrap(request, config)
    """

    _REGISTRY: Dict[tuple, type] = {
        ('python', 'poetry'): PythonPoetryBootstrapper,
        ('java',   'maven'):  JavaMavenBootstrapper,
        # Register additional bootstrappers here:
        # ('python', 'pip'):    PythonPipBootstrapper,
        # ('java',   'gradle'): JavaGradleBootstrapper,
        # ('node',   'npm'):    NodeNpmBootstrapper,
        # ('go',     'go_modules'): GoModulesBootstrapper,
    }

    @classmethod
    def create(
        cls,
        request: ScaffoldRequest,
        config: Dict[str, Any] = None
    ) -> BaseProjectBootstrapper:
        """
        Return instantiated bootstrapper for runtime + build_tool combination.
        Raises ValueError if combination is not registered.

        A source='json' | 'prompt' request that does not carry runtime and
        build_tool inline is resolved first (in place: the caller's dict
        becomes the resolved inline request), so selection never needs the two
        keys duplicated and bootstrap() does not resolve a second time.
        """
        if (request.get('source', 'inline') in ('json', 'prompt')
                and not (request.get('runtime') and request.get('build_tool'))):
            resolved = resolve_scaffold_request(request, config)
            request.clear()
            request.update(resolved)
        key = (request.get('runtime', ''), request.get('build_tool', ''))
        bootstrapper_cls = cls._REGISTRY.get(key)
        if not bootstrapper_cls:
            raise ValueError(
                f'No bootstrapper registered for runtime={key[0]}, '
                f'build_tool={key[1]}. '
                f'Registered: {list(cls._REGISTRY.keys())}'
            )
        return bootstrapper_cls(config=config)

    @classmethod
    def register(
        cls, runtime: str, build_tool: str, bootstrapper_cls: type
    ) -> None:
        """Register a new bootstrapper.  Called at module import time."""
        cls._REGISTRY[(runtime, build_tool)] = bootstrapper_cls


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  BootstrapAndGenerateWorkflow — composes P0 + A2C                       ║
# ╚══════════════════════════════════════════════════════════════════════════╝

class BootstrapAndGenerateWorkflow:
    """
    Orchestrates the full pipeline: P0 scaffold → A2C code generation.
    Reads the combined scaffold-config.json which contains both
    'scaffold' and 'a2c' sections.

    Can be used three ways:
      1. bootstrap_only=True   — Phase Zero only (no A2C)
      2. generate_only=True    — A2C only (project already bootstrapped)
      3. Default               — bootstrap then generate in sequence

    This is the BootstrapAndGenerateWorkflow, not a BaseWorkflow subclass,
    because it coordinates two independent frameworks rather than routing
    agent intent. A BaseWorkflow subclass is the correct pattern for
    multi-agent intent routing within a single framework.
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}

    def execute(
        self,
        scaffold_request: ScaffoldRequest,
        config: Dict[str, Any] = None,
        bootstrap_only: bool = False,
        generate_only: bool = False,
    ) -> Dict[str, Any]:
        """
        Execute the combined bootstrap + generate pipeline.

        Returns combined result:
          {
            'scaffold_result': ScaffoldResult,
            'generation_result': dict | None,   # None if bootstrap_only=True
            'success': bool,
            'errors': List[str]
          }
        """
        config = config or self.config
        result = {'success': False, 'errors': []}

        try:
            if not generate_only:
                bootstrapper = ProjectBootstrapperFactory.create(
                    scaffold_request, config
                )
                scaffold_result = bootstrapper.bootstrap(scaffold_request, config)
                result['scaffold_result'] = scaffold_result

                if not scaffold_result['success']:
                    result['errors'] += scaffold_result.get('errors', [])
                    return result

                if bootstrap_only:
                    result['success'] = True
                    return result

            # A2C generation phase — the second, explicit phase. P0 and A2C stay
            # composable siblings: this class only hands P0's dev_request to A2C's
            # SDLCWorkflow.execute(dev_request, config).
            dev_request = (
                (result.get('scaffold_result') or {}).get('dev_request')
                or config.get('a2c_dev_request')
            )
            if dev_request:
                if (config.get('a2c') or {}).get('handoff_only'):
                    result['generation_result'] = {'status': 'ready', 'dev_request': dev_request}
                else:
                    try:
                        from a2c_base import SDLCWorkflow, DevPlatformValidationService
                    except ImportError as e:            # a2c_base needs e2a_base on sys.path
                        raise RuntimeError(
                            'A2C phase needs a2c_base.py and e2a_base.py importable; set '
                            "config['a2c']['handoff_only']=True to stop after P0") from e
                    # Validation runs before the workflow (BaseValidationService tier).
                    validator = config.get('validation_service') or DevPlatformValidationService()
                    verdict = validator.validate('SDLCWorkflow', dev_request, config)
                    if not verdict['valid']:
                        result['generation_result'] = {'status': 'INVALID', 'validation': dict(verdict)}
                        result['errors'] += list(verdict['errors'])
                        return result
                    generation = SDLCWorkflow(config=config).execute(dict(dev_request), config)
                    result['generation_result'] = generation
                    if generation.get('errors') or generation.get('status') in (
                            'CONFLICT', 'FAILED_FINAL', 'RECOVERY_REQUIRED'):
                        result['errors'] += list(generation.get('errors') or [generation['status']])
                        return result
            elif generate_only:
                raise ValueError("generate_only=True needs config['a2c_dev_request']")

            result['success'] = True
            return result

        except Exception as e:
            logging.error(f'[BootstrapAndGenerateWorkflow] {e}')
            result['errors'].append(str(e))
            return result
