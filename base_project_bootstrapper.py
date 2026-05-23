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
import uuid
import time
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional

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
        trace_id = str(uuid.uuid4())
        start    = time.time()
        result: ScaffoldResult = {
            'success': False, 'trace_id': trace_id,
            'scaffolded_files': [], 'errors': []
        }

        try:
            # Step 1 — resolve
            src = request.get('source', 'inline')
            if src in ('json', 'prompt'):
                request = self._resolve_config(request, config, **kwargs)

            # Step 2 — validate
            if not self._validate_request(request, config, **kwargs):
                raise ValueError(
                    f'[{self.bootstrapper_name}] Validation failed — '
                    'check runtime, platform, build_tool, project_name'
                )

            # Step 3 — idempotency
            key = self.__generate_scaffold_key(request)
            request['scaffold_key'] = key
            if self.idempotency and self.__is_already_scaffolded(key, config):
                logging.info(f'[{self.bootstrapper_name}] Skip — already scaffolded: {key}')
                result.update({'success': True, 'scaffold_key': key})
                return result

            # Step 4 — plan
            request['scaffold_plan'] = self._plan_scaffold(request, config, **kwargs)

            # Step 5 — directory structure
            root = self.__resolve_output_path(request, config)
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

            # Step 8 — git config
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

            # Step 14 — validate output
            if not self._validate_output(result, config, **kwargs):
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
            result.update({'scaffold_key': key, 'success': True})
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
                result['dev_request'] = self.__build_dev_request(request, a2c_cfg)

            return result

        except Exception as e:
            return self._handle_error(e, request, result, config, **kwargs)

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

    @abstractmethod
    def _resolve_config(self, request, config=None, **kwargs) -> ScaffoldRequest:
        """
        Load ScaffoldRequest from external source.
          source='json':   call self.__load_json_config(request['config_path'])
          source='prompt': call self.__load_prompt_config(request['prompt'], config)
        Returns fully-populated ScaffoldRequest.
        """
        pass

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
        with open(config_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        scaffold = data.get('scaffold', data)
        scaffold['source'] = 'json'
        return scaffold

    def __load_prompt_config(self, prompt: str, config: dict) -> ScaffoldRequest:
        """
        Parse ScaffoldRequest from natural-language prompt via LLM.
        Routes to configured LLM via config['model_id'] — same as E2A __llm_call.
        Prompts the model to return ONLY a JSON ScaffoldRequest object.
        """
        # Implementation: call LLM with a structured extraction prompt,
        # parse JSON response into ScaffoldRequest TypedDict.
        # Omitted here — requires E2A BaseAgent or direct SDK integration.
        raise NotImplementedError(
            'Prompt resolution requires LLM integration. '
            'Provide source="json" or source="inline" for non-LLM use.'
        )

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

    def __is_already_scaffolded(self, key: str, config: dict) -> bool:
        """
        True if project directory already exists and is non-empty.
        Override config['scaffold_idempotency_store'] for external store (DynamoDB, Redis).
        """
        base = config.get('output_path', os.getenv('BOOTSTRAP_OUTPUT_PATH', './'))
        project_name = key.split(':')[0]
        d = Path(base) / project_name
        return d.exists() and any(d.iterdir())

    def __resolve_output_path(self, request: ScaffoldRequest, config: dict) -> str:
        """
        Resolve project root.
        Order: request['output_path'] > config['output_path'] >
               env BOOTSTRAP_OUTPUT_PATH > './'
        """
        base = (
            request.get('output_path')
            or config.get('output_path')
            or os.getenv('BOOTSTRAP_OUTPUT_PATH', './')
        )
        root = str((Path(base) / request.get('project_name', 'project')).resolve())
        Path(root).mkdir(parents=True, exist_ok=True)
        return root

    def __write_build_manifest(self, request, project_root: str, content: str) -> str:
        """Write build manifest to runtime-appropriate filename."""
        key      = (request.get('runtime','python'), request.get('build_tool','poetry'))
        filename = self.MANIFEST_FILENAMES.get(key, 'build.config')
        return self.__write_file(project_root, filename, content)

    def __build_dev_request(self, request: ScaffoldRequest, a2c_cfg: dict) -> dict:
        """
        Build A2C DevRequest from ScaffoldRequest + config['a2c'] section.
        Populates project_name, language, target_cloud automatically.
        Called at Step 16 when config['a2c']['enabled'] is True.
        """
        return {
            'project_name':   request.get('project_name'),
            'project_type':   a2c_cfg.get('project_type', ''),
            'mandatory_nfrs': a2c_cfg.get('mandatory_nfrs', []),
            'target_cloud':   request.get('platform', a2c_cfg.get('target_cloud', 'aws')),
            'language':       request.get('runtime', 'python'),
            'context':        a2c_cfg.get('context', ''),
        }


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
        return True

    def _resolve_config(self, request, config=None, **kwargs) -> ScaffoldRequest:
        if request.get('source') == 'json':
            loaded = self._BaseProjectBootstrapper__load_json_config(request['config_path'])
            request.update(loaded)
        return request

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
        deps_toml = '\n'.join(f'{d.split(">=")[0].split("==")[0].strip()} = "*"' for d in deps)
        dev_toml  = '\n'.join(f'{d.split(">=")[0].split("==")[0].strip()} = "*"' for d in dev)
        return f'''[tool.poetry]
name = "{name}"
version = "0.1.0"
description = ""
authors = ["Subham Gupta <subhamviky@gmail.com>"]
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
'''
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
        return {
            'Dockerfile': f'''# Multi-stage Python build — non-root runtime image
FROM python:{version}-slim AS builder
WORKDIR /build
RUN pip install poetry==1.8.3
COPY pyproject.toml poetry.lock* ./
RUN poetry config virtualenvs.in-project true && poetry install --no-dev --no-interaction

FROM python:{version}-slim AS runtime
WORKDIR /app
RUN groupadd -r appgroup && useradd -r -g appgroup -u 1001 appuser
COPY --from=builder /build/.venv /app/.venv
COPY src/ /app/src/
ENV PATH="/app/.venv/bin:$PATH"
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \\
  CMD curl -f http://localhost:8000/health || exit 1
CMD ["uvicorn", "{pkg}.main:app", "--host", "0.0.0.0", "--port", "8000"]
''',
            '.dockerignore': '.venv\n__pycache__\n*.pyc\n.env\n.git\ntests\n*.md\n'
        }

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
                    'group_id', 'artifact_id']
        if not all(k in request for k in required):
            logging.error(f'[{self.bootstrapper_name}] Missing: '
                          f'{[k for k in required if k not in request]}')
            return False
        if request['runtime'] != 'java' or request['build_tool'] != 'maven':
            return False
        return True

    def _resolve_config(self, request, config=None, **kwargs) -> ScaffoldRequest:
        if request.get('source') == 'json':
            loaded = self._BaseProjectBootstrapper__load_json_config(request['config_path'])
            request.update(loaded)
        return request

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
        dep_xml = '\n'.join(
            f'        <dependency>\n'
            f'            <groupId>org.springframework.boot</groupId>\n'
            f'            <artifactId>spring-boot-starter-{d}</artifactId>\n'
            f'        </dependency>'
            for d in deps
        )
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
''',
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
        return {
            'Dockerfile': f'''# Multi-stage Java build — non-root runtime image
FROM eclipse-temurin:{jv}-jdk-alpine AS builder
WORKDIR /build
COPY pom.xml .
COPY src ./src
RUN apk add --no-cache maven && mvn clean package -DskipTests

FROM eclipse-temurin:{jv}-jre-alpine AS runtime
WORKDIR /app
RUN addgroup -S appgroup && adduser -S appuser -G appgroup -u 1001
COPY --from=builder /build/target/*.jar app.jar
USER appuser
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \\
  CMD wget -q -O- http://localhost:8080/actuator/health || exit 1
ENTRYPOINT ["java", "-jar", "app.jar"]
''',
            '.dockerignore': 'target/\n.git\n*.md\n.idea/\n*.iml\n'
        }

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
        """
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

            # A2C generation phase
            dev_request = (
                result.get('scaffold_result', {}).get('dev_request')
                or config.get('a2c_dev_request')
            )
            if dev_request:
                # Import lazily to avoid circular dependency
                # from src.a2c.sdlc_assistant_agent import SDLCAssistantAgent
                # sdlc = SDLCAssistantAgent(config=config)
                # generation_result = await sdlc.run(dev_request, config)
                # result['generation_result'] = generation_result
                logging.info('[BootstrapAndGenerateWorkflow] A2C handoff ready — '
                             f'dev_request populated: {list(dev_request.keys())}')
                result['generation_result'] = {'status': 'ready', 'dev_request': dev_request}

            result['success'] = True
            return result

        except Exception as e:
            logging.error(f'[BootstrapAndGenerateWorkflow] {e}')
            result['errors'].append(str(e))
            return result
