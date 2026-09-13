# Wiki workflow action review

Phase 3 issue #281 also covers the separate `docs/wiki` source branch. Its two
executable workflows are Wiki source validation and Wiki publication. Four action
references resolve to two reviewed upstream identities:

| Action | Upstream ref | Commit |
| --- | --- | --- |
| `actions/checkout` | `v4` | `11d5960a326750d5838078e36cf38b85af677262` |
| `actions/setup-python` | `v5` | `a26af69be951a213d495a4c3e4e4022e16d87065` |

Both commits were verified against their official GitHub repositories on
2026-09-13. The maintained checker and regression tests are shared with product
PR #289. The checker parses executable YAML fields, follows repository-local
composite and reusable workflow dependencies, and rejects mutable references,
ambiguous keys, missing local actions and unsafe paths. Its parser dependency is
pinned in `visuals/workflow-requirements.txt`. Source CI runs both the policy and
its tests. Publication checks the policy before generating or publishing assets.

Repository maintainers own updates. Resolve the intended upstream release to its
full commit, review the upstream diff and release notes, update the readable
comments and this inventory, then run the policy, its tests and Wiki validation.
Keep updates reviewable; do not auto-approve action code. Roll back to the previous
reviewed commit if an update fails. When the shared checker changes, review and
port it on this branch as a dedicated Wiki change.

Pinning the entry action does not authenticate downloaded Python/tool
distributions or every transitive network dependency. Existing explicit Python
and diagram dependency versions remain separate review responsibilities. Source
validation keeps read-only permissions; publication retains its existing
`docs/wiki`-only guard, serialized publication and exact source/review checks.
No Wiki content belongs in `development`.
