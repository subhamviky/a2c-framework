"""GeneratorFactory — generator_type -> generator class (G2C Framework
Reference §10.1). Same approved-list pattern as E2A agent routing."""
from typing import Any, Dict, Optional, Union

from e2a_abstract_class_generator import E2AAbstractClassGenerator
from a2c_abstract_class_generator import A2CAbstractClassGenerator
from e2a_inherited_class_generator import E2AInheritedClassGenerator
from a2c_inherited_class_generator import A2CInheritedClassGenerator


class GeneratorFactory:
    _REGISTRY: Dict[str, type] = {
        "e2a_abstract": E2AAbstractClassGenerator,
        "a2c_abstract": A2CAbstractClassGenerator,
        "e2a_inherited": E2AInheritedClassGenerator,
        "a2c_inherited": A2CInheritedClassGenerator,
    }

    @classmethod
    def create(cls, request: Union[dict, str], config: Optional[Dict[str, Any]] = None, **kwargs):
        """Instantiate the generator for request['generator_type'] (a bare
        type string is also accepted). Unknown type -> ValueError."""
        gen_type = request.get("generator_type") if isinstance(request, dict) else request
        gen_cls = cls._REGISTRY.get(gen_type)
        if gen_cls is None:
            raise ValueError(f"Unknown generator_type: {gen_type}. "
                             f"Registered: {list(cls._REGISTRY)}")
        return gen_cls(config=config)

    @classmethod
    def register(cls, gen_type: str, generator_cls: type) -> None:
        """Register a generator at import time. The type must also be in the
        generator's APPROVED_GENERATOR_TYPES for _apply_policy to admit it."""
        cls._REGISTRY[gen_type] = generator_cls
