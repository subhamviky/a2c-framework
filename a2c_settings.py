"""App settings declared in the request (A2C v1.2, wave C design note C-02, item A-3).

    "a2c_sdlc": {"settings": [
        {"name": "TABLE_NAME", "default": "reconciliation"},
        {"name": "SETTLEMENT_API_URL"},                     # no default: required at deploy time
        {"name": "BANK_API_TOKEN", "secret": true}          # a reference to the cloud's secret store
    ]}

Each setting becomes a Terraform variable, an environment variable of the container or
function in all three cloud templates, a line in .env.example and an entry of the
generated config loader; a generated `terraform test` asserts that it reaches the
runtime. A secret is declared in the cloud's secret store and referenced; Terraform never
holds its value.
"""
import json
import re
from typing import Any, Dict, List

NAME = re.compile(r'^[A-Z][A-Z0-9_]{0,62}$')


class SettingsError(ValueError):
    """The request declares a setting that cannot be generated."""


def normalize(settings: Any) -> List[Dict[str, Any]]:
    """Validate and normalise `a2c_sdlc.settings`; refuse what cannot be generated."""
    out, seen = [], set()
    for raw in settings or []:
        item = {'name': raw} if isinstance(raw, str) else dict(raw)
        name = str(item.get('name', ''))
        if not NAME.match(name):
            raise SettingsError(f"setting name {name!r}: use UPPER_SNAKE_CASE (letters, digits, _)")
        if name in seen:
            raise SettingsError(f'setting {name} is declared twice')
        seen.add(name)
        secret = bool(item.get('secret', False))
        if secret and item.get('default') is not None:
            raise SettingsError(f'secret {name} cannot have a default: its value lives in the secret store')
        default = item.get('default')
        out.append({'name': name, 'secret': secret, 'default': None if default is None else str(default),
                    'description': str(item.get('description') or f'App setting {name}.')})
    return out


def var_name(setting: Dict[str, Any]) -> str:
    return 'setting_' + setting['name'].lower()


def secret_id(setting: Dict[str, Any]) -> str:
    return setting['name'].lower().replace('_', '-')


def _hcl(value: str) -> str:
    return json.dumps(value)            # a JSON string literal is a valid HCL string literal


# ----------------------------------------------------------------- Terraform
def terraform(cloud: str, settings: List[Dict[str, Any]]) -> Dict[str, str]:
    """The placeholders of the cloud template, rendered for these settings ('' when none)."""
    plain = [s for s in settings if not s['secret']]
    secrets = [s for s in settings if s['secret']]
    variables = ''.join(
        f'\nvariable "{var_name(s)}" {{\n  type        = string\n  description = {_hcl(s["description"])}\n'
        + (f'  default     = {_hcl(s["default"])}\n' if s['default'] is not None else '')
        + '}\n' for s in plain)
    env = resources = arns = ''
    if cloud == 'gcp':
        env = ''.join(f'      env {{\n        name  = "{s["name"]}"\n        value = var.{var_name(s)}\n      }}\n'
                      for s in plain)
        env += ''.join(
            f'      env {{\n        name = "{s["name"]}"\n        value_source {{\n          secret_key_ref {{\n'
            f'            secret  = google_secret_manager_secret.{var_name(s)}.secret_id\n'
            f'            version = "latest"\n          }}\n        }}\n      }}\n' for s in secrets)
        resources = ''.join(
            f'# {s["name"]}: the value is added out of band (no secret value in Terraform).\n'
            f'resource "google_secret_manager_secret" "{var_name(s)}" {{\n'
            f'  secret_id = "${{local.name}}-{secret_id(s)}"\n  labels    = local.labels\n'
            f'  replication {{\n    auto {{}}\n  }}\n}}\n\n'
            f'resource "google_secret_manager_secret_iam_member" "{var_name(s)}" {{\n'
            f'  secret_id = google_secret_manager_secret.{var_name(s)}.id\n'
            f'  role      = "roles/secretmanager.secretAccessor"\n'
            f'  member    = "serviceAccount:${{google_service_account.app.email}}"\n}}\n\n' for s in secrets)
    elif cloud == 'aws':
        pairs = [(s['name'], f'var.{var_name(s)}') for s in plain] + \
                [(s['name'] + '_SECRET_ARN', f'aws_secretsmanager_secret.{var_name(s)}.arn') for s in secrets]
        width = max((len(k) for k, _ in pairs), default=0)
        # a blank line first: terraform fmt aligns '=' only within a group of consecutive lines
        env = ('\n' + ''.join(f'      {k.ljust(width)} = {v}\n' for k, v in pairs)) if pairs else ''

        resources = ''.join(
            f'# {s["name"]}: the value is added out of band; the function reads it by ARN.\n'
            f'resource "aws_secretsmanager_secret" "{var_name(s)}" {{\n'
            f'  name = "${{local.name}}/{secret_id(s)}"\n  tags = local.tags\n}}\n\n' for s in secrets)
        arns = ''.join(f', aws_secretsmanager_secret.{var_name(s)}.arn' for s in secrets)
    elif cloud == 'azure':
        env = ''.join(f'      env {{\n        name  = "{s["name"]}"\n        value = var.{var_name(s)}\n      }}\n'
                      for s in plain)
        env += ''.join(f'      env {{\n        name        = "{s["name"]}"\n        secret_name = "{secret_id(s)}"\n'
                       f'      }}\n' for s in secrets)
        # a Key Vault secret of the same name holds the value, added out of band
        resources = ''.join(
            f'  secret {{\n    name                = "{secret_id(s)}"\n'
            f'    identity            = azurerm_user_assigned_identity.app.id\n'
            f'    key_vault_secret_id = "${{azurerm_key_vault.app.vault_uri}}secrets/{secret_id(s)}"\n  }}\n\n'
            for s in secrets)
    return {'settings_variables': variables, 'settings_env': env, 'settings_resources': resources,
            'settings_secret_arns': arns, **terraform_test(cloud, settings)}


def terraform_test(cloud: str, settings: List[Dict[str, Any]]) -> Dict[str, str]:
    """Test values for required settings and one assertion per setting."""
    plain = [s for s in settings if not s['secret']]
    required = [s for s in plain if s['default'] is None]
    width = max((len(var_name(s)) for s in required), default=0)
    values = ('\n' + ''.join(f'  {var_name(s).ljust(width)} = "test-{s["name"].lower()}"\n' for s in required)
              if required else '')
    asserts = ''
    for s in settings:
        if cloud == 'aws':
            key = s['name'] + ('_SECRET_ARN' if s['secret'] else '')
            condition = f'contains(keys(aws_lambda_function.app.environment[0].variables), "{key}")'
        elif cloud == 'gcp':
            condition = (f'contains([for e in google_cloud_run_v2_service.app.template[0].containers[0].env : e.name], '
                         f'"{s["name"]}")')
        else:
            condition = (f'contains([for e in azurerm_container_app.app.template[0].container[0].env : e.name], '
                         f'"{s["name"]}")')
        asserts += (f'\n  assert {{\n    condition     = {condition}\n'
                    f'    error_message = "The setting {s["name"]} must reach the runtime."\n  }}\n')
    block = f'variables {{{values}}}\n\n' if values else ''
    if cloud == 'aws':                  # the AWS test has no variables block of its own
        return {'settings_test_variables': '', 'settings_test_variables_block': block,
                'settings_test_asserts': asserts}
    return {'settings_test_variables': values, 'settings_test_variables_block': '',
            'settings_test_asserts': asserts}


# ------------------------------------------------------------ the application
def env_example(settings: List[Dict[str, Any]]) -> str:
    if not settings:
        return ''
    lines = ['', '# App settings (declared in the A2C request)']
    for s in settings:
        if s['secret']:
            lines.append(f'# {s["name"]}: a secret; set it in your shell or the cloud secret store, never here')
        else:
            lines.append(f'{s["name"]}={s["default"] or ""}')
    return '\n'.join(lines) + '\n'


def python_module(settings: List[Dict[str, Any]]) -> str:
    """src/<package>/settings.py: read every declared setting once, fail naming the missing ones."""
    spec = ',\n    '.join(f'{s["name"]!r}: {s["default"]!r}' for s in settings)
    secrets = sorted(s['name'] for s in settings if s['secret'])
    return f'''"""App settings declared in the A2C request (generated; edit the request, not this file).

load_settings() reads each setting once from the environment and fails at start-up,
naming every missing required setting. A secret is read from NAME, or on AWS Lambda from
the secret store through NAME_SECRET_ARN.
"""
import os
from typing import Dict, Optional

DECLARED: Dict[str, Optional[str]] = {{
    {spec}
}}
SECRETS = {secrets!r}


class MissingSettings(RuntimeError):
    """Required settings are not set."""


def _secret_from_arn(name: str) -> Optional[str]:
    arn = os.getenv(f"{{name}}_SECRET_ARN")
    if not arn:
        return None
    import boto3                                   # only on AWS
    return boto3.client("secretsmanager").get_secret_value(SecretId=arn)["SecretString"]


def load_settings(environ=None) -> Dict[str, str]:
    environ = os.environ if environ is None else environ
    values, missing = {{}}, []
    for name, default in DECLARED.items():
        value = environ.get(name) or (_secret_from_arn(name) if name in SECRETS and environ is os.environ
                                      else None) or default
        if value is None:
            missing.append(name)
        else:
            values[name] = value
    if missing:
        raise MissingSettings("missing required settings: " + ", ".join(missing))
    return values
'''


def python_test(package: str, settings: List[Dict[str, Any]]) -> str:
    required = [s['name'] for s in settings if s['default'] is None]
    full = {s['name']: s['default'] or 'x' for s in settings}
    return f'''"""Generated by A2C: every declared setting is read; missing required ones are named."""
import pytest

from {package}.settings import MissingSettings, load_settings


def test_all_settings_are_read():
    assert set(load_settings({full!r})) == {set(full)!r}


def test_missing_required_settings_are_named():
    required = {required!r}
    if not required:
        return
    with pytest.raises(MissingSettings) as error:
        load_settings({{}})
    assert all(name in str(error.value) for name in required)
'''


def java_yaml(settings: List[Dict[str, Any]]) -> str:
    """An `app:` section for application.yml: Spring fails at start-up on a missing
    required placeholder, naming it."""
    if not settings:
        return ''
    lines = ['', '# App settings (declared in the A2C request)', 'app:']
    for s in settings:
        key = s['name'].lower().replace('_', '-')
        value = f'${{{s["name"]}}}' if s['default'] is None else f'${{{s["name"]}:{s["default"]}}}'
        lines.append(f"  {key}: '{value}'")
    return '\n'.join(lines) + '\n'
