"""E2AInheritedClassGenerator — one call from request to an inherited E2A
agent/workflow class inside a P0-scaffolded project (G2C Framework Reference
§7). Phases are in inherited_generator.BaseInheritedClassGenerator."""
from inherited_generator import BaseInheritedClassGenerator


class E2AInheritedClassGenerator(BaseInheritedClassGenerator):
    generator_name = "E2AInheritedClassGenerator"
    generator_type = "e2a_inherited"
    critic_type = "e2a_inherited"
    kind = "e2a_inherited"
