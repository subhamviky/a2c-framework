from e2a_abstract_class_generator import E2AAbstractClassGenerator
from a2c_abstract_class_generator import A2CAbstractClassGenerator
from e2a_inherited_class_generator import E2AInheritedClassGenerator
from a2c_inherited_class_generator import A2CInheritedClassGenerator

class GeneratorFactory:
    _REGISTRY = {
        "e2a_abstract": E2AAbstractClassGenerator,
        "a2c_abstract": A2CAbstractClassGenerator,
        "e2a_inherited": E2AInheritedClassGenerator,
        "a2c_inherited": A2CInheritedClassGenerator,
    }

    @classmethod
    def create(cls, generator_type, **kwargs):
        if generator_type not in cls._REGISTRY:
            raise ValueError(f"Unknown generator_type: {generator_type}")
        return cls._REGISTRY[generator_type](**kwargs)
