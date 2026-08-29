# Managed GitHub Wiki source

This directory is the complete, reviewed source for the Latent Service Fabric
GitHub Wiki. It is intentionally published only from a local developer command;
there is no workflow that can update the Wiki automatically.

The pages in `wiki/pages/` are copied to the root of the GitHub Wiki repository.
Every managed Markdown page starts with `<!-- LSF-WIKI-MANAGED -->`. The local
publisher replaces those pages and the listed legacy managed files while leaving
unrecognized Wiki pages alone.

The three prominent Phase 0 pages also carry a gate-status marker. Before a
default-source publication, the publisher compares those markers with
`docs/phase-0-completion.md` and refuses a mismatch. Update the Wiki only after
the authoritative document and actual receipt justify the new state.

## Local publication protocol

From a clean checkout with Python 3.13 or newer and Git credentials capable of
pushing to the repository Wiki:

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

`wiki/legacy-managed-files.txt` is a finite inventory of pages and assets
published by the retired workflow. It permits this refresh to remove known
obsolete material without deleting Wiki pages outside LSF's managed set.

The Wiki is explanatory and non-normative. The `development` branch of the
main repository remains the authority for code, contracts, evidence, roadmap
state, and authorization status.
