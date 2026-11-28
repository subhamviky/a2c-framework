# Solution overview

*One page.*

**The problem.** AI coding tools speed up code but not architecture: generated services drift from the intended structure, omit non-functional requirements, and ship without pipelines or gates.

**What it is.** A generation framework (A2C, with G2C for services and P0 for project starters) that turns one declared request into a project with E2A's safety order, infrastructure as code, a CI/CD pipeline with a vulnerability scan and a release gate, and evaluation sets, with critics that review the output and provenance for every run. Four projects were scaffolded this way.

**Evidence.** The CHANGELOG lists what live runs found and fixed (workflow commits, valid YAML, the image scanner); the assistant's pipeline is the generated one.

**Limits.** Generated Terraform is validated by the generated project's checks; the critics are heuristics; one maintainer.
