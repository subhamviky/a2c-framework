# Design documents

Detailed HLD and LLD documents for the frameworks in this repository. Each folder holds the document as Markdown, its diagrams (PNG images plus PlantUML and Graphviz sources) and a Word copy.

| Folder | Framework | Read it for |
|---|---|---|
| [`p0/`](p0/P0_FRAMEWORK_DESIGN.md) | P0 — Project Bootstrap | `BaseProjectBootstrapper`, the 16-step scaffold, the `dev_request` hand-off |
| [`g2c/`](g2c/G2C_FRAMEWORK_DESIGN.md) | G2C — Generator-to-Class | `BaseGeneratorAgent`, abstract and inherited generators, the critic, the workflow and router |
| [`a2c/`](a2c/A2C_FRAMEWORK_DESIGN.md) | A2C — Architecture-to-Code | `SDLCAssistantAgent`, the specialist agents, `CodeCriticAgent`, `SDLCWorkflow` |

The family-level document that ties these together with E2A and AI-DLC is in the `e2a-framework` repository under `docs/design/system/`.

The Python files remain the reference for line-level detail.
