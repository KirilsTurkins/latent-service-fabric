<!-- LSF-WIKI-MANAGED -->
# Glossary

| Term | Definition |
|---|---|
| Activation | A bounded execution attempt for one invocation. |
| Affine lease | A non-cloneable cell lease whose issuer controls release/quarantine authority. |
| Capsule | A Component Model binary plus immutable metadata and contract identity. |
| Cell | A generic reusable node allocation slot; never a permanent service instance. |
| Completion receipt | Machine-readable result from the Phase 0 gate, including evidence verification and authorization state. |
| Domain error | A contract-declared service result. |
| Execution identity | Canonical identity of source/fixture/tooling inputs relevant to measured execution. |
| Fresh store | Invocation-owned Wasmtime state that is discarded after an activation. |
| Gate | The fail-closed validation that decides whether evidence authorizes the next handoff. |
| Native-Linux evidence | Calibration, profile, or soak data gathered on an accepted clean Linux host/VM. |
| Platform error | An infrastructure or execution failure outside a service’s declared domain result. |
| Prepared component | Bounded node-owned state ready for invocation; distinct from a leased cell/store. |
| Quarantine | Removing a cell from reusable capacity when safe cleanup is not proven. |
| Release | Immutable capsule artifact represented by content identity. |
| Revision | Release plus deployment configuration. |
| Route | A rule selecting a revision for new work. |
| Soak | Long-running repeated-work evidence used to study bounded resource behavior. |
| WIT | WebAssembly Interface Types; the capsule-facing contract authority. |
