"""a2c_assets — data files shipped with the A2C/G2C/P0 package.

prompts/    versioned generator system prompts (G2C)
templates/  deterministic artifacts served by the A2C template LLM
            (Terraform per cloud, GitHub Actions, code modules per language)
"""
from pathlib import Path

ASSETS_DIR = Path(__file__).resolve().parent
PROMPTS_DIR = ASSETS_DIR / 'prompts'
TEMPLATES_DIR = ASSETS_DIR / 'templates'


def read_template(relative_path: str) -> str:
    """Text of a template under templates/, e.g. 'terraform/aws.tf'."""
    return (TEMPLATES_DIR / relative_path).read_text(encoding='utf-8')