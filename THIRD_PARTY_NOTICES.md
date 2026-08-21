# Third-party notices

AgentLoopGate interoperates with, tests against, or adapts the following pinned upstream
projects. Their names and marks remain the property of their respective owners.

| Project | Pinned version / revision | License | Use |
|---|---|---|---|
| DeepSeek Harness | `0.1.0-rc.8` / `141eb6fef83422698aef7a981029e843e8161534` | MIT, Copyright 2026 DeepSeek | Optional plugin host and development/test dependency |
| τ²/τ³-bench | `1.0.1` / `fc0055dc4e0a316c3f83133267fbd6faaa770992` | MIT, Copyright 2025 Sierra Research | Optional banking benchmark adapter |
| Agentic Harness Engineering | `0.1.0` / `8b2a55d97590363fe50c3cc6b5e833b020a4bb4c` | MIT, Copyright 2026 Jiahang Lin | Optional external updater adapter |

The upstream repositories are not vendored into the AgentLoopGate source distribution. Local
`.cache/` checkouts and installed package trees are ignored. Transitive Python and npm packages
retain the licenses shipped in their own distributions and lockfiles.
