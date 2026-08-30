# Managed GitHub Wiki source

This directory is the complete, reviewed source for the Latent Service Fabric
GitHub Wiki. It is intentionally published only from a local developer command;
there is no workflow that can update the Wiki automatically.

The pages in `wiki/pages/` are copied to the root of the GitHub Wiki repository.
Every managed Markdown page starts with `<!-- LSF-WIKI-MANAGED -->`. The local
publisher replaces those pages and the listed legacy managed files while leaving
unrecognized Wiki pages alone.

The three prominent Phase 0 pages also carry a gate-status marker. Before a
publication attempt, the publisher compares those markers with
`docs/phase-0-completion.md` and refuses a mismatch. Update the Wiki only after
the authoritative document and actual receipt justify the new state.

The checked-in source currently reflects the August 30 authorized native-Linux
receipt. It must be changed again if a later authoritative completion document
records a different state.

## Local publication protocol

From a clean checkout of the development branch, with Python 3.13 or newer
and Git credentials capable of pushing to the repository Wiki:

```bash
# Validate only; this does not clone, commit, or contact the Wiki.
python3 tools/update_wiki.py

# Clone the Wiki to a temporary directory and show the exact staged change set.
python3 tools/update_wiki.py --plan

# After reviewing the plan, create one Wiki commit and push it.
python3 tools/update_wiki.py --apply
```

Use normal Git credential management or an SSH remote. Do not embed an access
token in a command line, source file, or commit.

Planning always uses an isolated temporary Wiki clone. An existing local Wiki
checkout may be supplied only to the explicit apply operation, and it must be
clean, on the selected branch, and pointed at the selected credential-free
Wiki remote.

`wiki/legacy-managed-files.txt` is a finite inventory of pages and assets
published by the retired workflow. It permits this refresh to remove known
obsolete material without deleting Wiki pages outside LSF's managed set.

The Wiki is explanatory and non-normative. The `development` branch of the
main repository remains the authority for code, contracts, evidence, roadmap
state, and authorization status.

## Source conventions

- Write every managed page as a self-contained explanation of what is
  implemented, what is recorded evidence, and what remains planned.
- Keep diagrams as checked-in, accessible SVGs with a title, description,
  `role="img"`, a view box, filename-scoped internal IDs, and only local
  references. Do not rely on raster screenshots, Mermaid rendering, remote
  image assets, scripts, or external fonts/styles.
- Use the project-wide visual language: a 1440 x 760 purple-to-blue canvas,
  system-ui text, 24 px rounded cards, blue/purple factual or execution cards,
  amber blockers, green only for a verified pass or authorized result, and
  slate for excluded or later scope. The canonical detailed reference is
  `docs/svg-style.md` on the development source branch.
- Use valid Wiki links for managed pages and development-branch links for
  repository authorities. The local validator checks both before publication.
- Treat the Phase 0 markers as a safety boundary: update them only when the
  authoritative completion document and receipt genuinely support the change.
