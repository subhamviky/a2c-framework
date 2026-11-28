# Test strategy: a2c-framework

| Layer | What it proves |
|---|---|
| Smoke tests | each generator and the CLI (`a2c_cli`), the layout, settings and contracts, the template LLM used offline |
| Packaging check | the installed package works, not only the checkout |
| Generate, build, probe | a service is generated, its image built and run, and probed (Python), plus a Java service built against e2a-java |
| Conformance | generated services pass E2A's strict conformance |
| Output validity | generated YAML and Node code parse (`tsc`, YAML tests added after findings) |
| Real runs | consuming projects (settlement, reconciliation, O2C, the assistant) were scaffolded with it; the first live run of each feature fed the CHANGELOG |

Gaps: generated infrastructure is validated by Terraform's own checks in the generated project, not by A2C's tests; critics are heuristics.
