"""generator_api_router.py — FastAPI exposure for G2C (G2C Framework
Reference §11.1). Parameter binding and response mapping only; no business
logic. Endpoints are synchronous so FastAPI runs each generation in its
threadpool (generation is blocking and long-running).

    app.include_router(router)
    configure_generator(config)      # llm_service, idempotency_store, ...
"""
from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, HTTPException

from developer_platform_workflow import DeveloperPlatformWorkflow
from generator_factory import GeneratorFactory

router = APIRouter(prefix="/api/v1/g2c", tags=["G2C Generator"])

_CONFIG: Dict[str, Any] = {}
_WORKFLOW = {"instance": None}


def configure_generator(config: Dict[str, Any]) -> None:
    """Bind the generator config once at start-up. One workflow instance is
    kept so its shared-artifact registry outlives single requests."""
    _CONFIG.clear()
    _CONFIG.update(config or {})
    _WORKFLOW["instance"] = DeveloperPlatformWorkflow(config=_CONFIG)


def get_generator_config() -> Dict[str, Any]:
    return _CONFIG


def _workflow() -> DeveloperPlatformWorkflow:
    if _WORKFLOW["instance"] is None:
        _WORKFLOW["instance"] = DeveloperPlatformWorkflow(config=_CONFIG)
    return _WORKFLOW["instance"]


def _run(request: Dict[str, Any], config: Dict[str, Any], via_workflow: bool) -> Dict[str, Any]:
    try:
        if via_workflow:
            return _workflow().generate(request, config)
        return GeneratorFactory.create(request, config).generate(request, config)
    except (ValueError, PermissionError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/health")
def health_check():
    return {"status": "ok"}


@router.post("/generate")
def generate(request: Dict[str, Any] = Body(...), config: Dict[str, Any] = Depends(get_generator_config)):
    """Universal endpoint; routes on generator_type."""
    return _run(request, config, via_workflow=True)


@router.post("/e2a/abstract")
def generate_e2a_abstract(request: Dict[str, Any] = Body(...),
                          config: Dict[str, Any] = Depends(get_generator_config)):
    return _run({**request, "generator_type": "e2a_abstract"}, config, via_workflow=False)


@router.post("/a2c/abstract")
def generate_a2c_abstract(request: Dict[str, Any] = Body(...),
                          config: Dict[str, Any] = Depends(get_generator_config)):
    return _run({**request, "generator_type": "a2c_abstract"}, config, via_workflow=False)


@router.post("/e2a/inherited")
def generate_e2a_inherited(request: Dict[str, Any] = Body(...),
                           config: Dict[str, Any] = Depends(get_generator_config)):
    return _run({**request, "generator_type": "e2a_inherited"}, config, via_workflow=True)


@router.post("/a2c/inherited")
def generate_a2c_inherited(request: Dict[str, Any] = Body(...),
                           config: Dict[str, Any] = Depends(get_generator_config)):
    return _run({**request, "generator_type": "a2c_inherited"}, config, via_workflow=True)
