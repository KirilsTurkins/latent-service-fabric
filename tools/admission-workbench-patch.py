"""One-shot source edits for the feature-branch workbench; self-removes."""
from pathlib import Path


def replace_once(path, old, new):
    file = Path(path)
    source = file.read_text()
    assert source.count(old) == 1, (path, old, source.count(old))
    file.write_text(source.replace(old, new, 1))


compiler = 'crates/latent-control-store/src/deployments/compiler.rs'
replace_once(compiler, 'use std::collections::{BTreeMap, BTreeSet};', 'mod admission;\n\nuse std::collections::{BTreeMap, BTreeSet};')
replace_once(compiler, '    endpoints: BTreeMap<EndpointKey, WeightedSet>,', '    endpoints: BTreeMap<EndpointKey, WeightedSet>,\n    admission_policies: BTreeMap<latent_core::RevisionId, latent_routing::RevisionAdmissionPolicy>,')
replace_once(compiler, '    let mut route_entries = 0_usize;', '    let mut admission_policies = BTreeMap::new();\n    let mut route_entries = 0_usize;')
replace_once(compiler, '        let revision = Arc::new(RevisionRoute {\n            revision: deployment_revision_id(deployment)?,', '        let revision_id = deployment_revision_id(deployment)?;\n        admission::retain_policy(\n            &mut admission_policies,\n            revision_id.clone(),\n            deployment,\n            &artifact.manifest.execution,\n            &mut metadata_budget,\n        )?;\n        let revision = Arc::new(RevisionRoute {\n            revision: revision_id,')
replace_once(compiler, '        endpoints: weighted,', '        endpoints: weighted,\n        admission_policies,')
replace_once('crates/latent-control-store/src/deployments/tests.rs', 'mod fixtures;', 'mod admission;\nmod fixtures;')
lock = Path('Cargo.lock')
source = lock.read_text()
start = source.index('name = "latent-control-store"\n')
end = source.index('[[package]]', start)
entry = source[start:end]
assert '"latent-admission"' not in entry
entry = entry.replace('dependencies = [\n', 'dependencies = [\n "latent-admission",\n', 1)
lock.write_text(source[:start] + entry + source[end:])
Path(__file__).unlink()
