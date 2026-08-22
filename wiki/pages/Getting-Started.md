# Getting Started

> **Document role:** Explanatory onboarding. The authoritative build, validation, and contribution rules are in the main repository.

## Understand the current scope

LSF is not yet an installable service platform. The repository contains:

- authoritative WIT, Protobuf, JSON Schema, Rust trait, and SDK surfaces;
- accepted architecture decisions and detailed protocol documents;
- compile-smoke and contract validation tooling;
- placeholder application entry points;
- conformance, security, compatibility, chaos, integration, leak, and benchmark specifications.

It does not yet contain a complete activation runtime or production deployment.

## Choose a path

### Learn the model

1. Read [[Core-Concepts|Core concepts]].
2. Read [[Architecture]].
3. Follow one invocation through [[Activation-Lifecycle|Activation lifecycle]].
4. Review [[Security-and-Isolation|Security and isolation]] and [[State-and-Effects|State and effects]].
5. Use [[Glossary]] while reading canonical documents.

### Evaluate the engineering claim

Start with the resource invariant and then review:

1. [[Execution-Cells|Execution cells]]
2. [[Testing-and-Benchmarks|Testing and benchmarks]]
3. [Test invariants](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/testing/invariants.md)
4. [Idle-scaling benchmark specifications](https://github.com/KirilsTurkins/latent-service-fabric/tree/release/benchmarks/idle-scaling)
5. [Memory-reclamation benchmark specifications](https://github.com/KirilsTurkins/latent-service-fabric/tree/release/benchmarks/memory-reclamation)

The central claim is not established by interface compilation alone. It requires measurements showing that dormant service count does not change operating-system process, thread, socket, or execution-cell counts.

### Contribute to the repository

Read [CONTRIBUTING.md](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/CONTRIBUTING.md) before changing contracts or architectural seams. Determine whether the change is:

- an ADR-worthy architectural decision;
- an RFC requiring review before contract changes;
- an interface change;
- an implementation behind an accepted interface;
- an experiment that must remain under `research/`.

Then follow [[Development-Workflow|Development workflow]] and [[Design-Governance|Design governance]].

## Validate a clean checkout

The supported reference environment is Linux or WSL. Install the exact versions documented in the [toolchain baseline](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/development/toolchain.md), then run:

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --requirement tools/requirements.lock
make validate
```

The validation target checks formatting, compilation, Clippy, tests, WIT parsing and generated bindings, Protobuf lint and descriptor generation, JSON Schemas and examples, and all language SDK surfaces.

Passing validation establishes source consistency and reproducibility. It does not establish runtime correctness, isolation, performance, or the zero-idle-allocation invariant.

## Repository entry points

| Need | Start here |
|---|---|
| Project summary | [README](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/README.md) |
| Architectural source map | [ARCHITECTURE.md](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/ARCHITECTURE.md) |
| Contract map | [API surface](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/api-surface.md) |
| Exact tool versions | [Toolchain baseline](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/development/toolchain.md) |
| Validation scope | [VALIDATION.md](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/VALIDATION.md) |
| Contribution rules | [CONTRIBUTING.md](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/CONTRIBUTING.md) |
| Planned phases | [Engineering roadmap](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/roadmap.md) |
| Open work | [Issues](https://github.com/KirilsTurkins/latent-service-fabric/issues) |

## Before implementing a subsystem

Confirm four things:

1. Which contract form is authoritative: WIT, Protobuf, JSON Schema, or an internal Rust trait?
2. Which ADRs constrain the design?
3. Which resource, security, compatibility, and failure invariants apply?
4. Which conformance test or benchmark proves the intended behavior?

Continue with [[Repository-Map|Repository map]] for the source layout.
