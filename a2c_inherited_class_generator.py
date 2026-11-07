"""A2CInheritedClassGenerator — E2A and A2C bases (generated if needed), a
P0 scaffold and a team SDLCAssistantAgent subclass that adds its own NFRs on
top of A2C's mandatory set (G2C Framework Reference §8). It produces the
class file only: Terraform and CI/CD come from running A2C's SDLCWorkflow
with a DevRequest in a second, explicit phase."""
from inherited_generator import BaseInheritedClassGenerator


class A2CInheritedClassGenerator(BaseInheritedClassGenerator):
    generator_name = "A2CInheritedClassGenerator"
    generator_type = "a2c_inherited"
    critic_type = "a2c_inherited"
    kind = "a2c_inherited"
