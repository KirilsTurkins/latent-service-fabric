"""Apply the reviewed PR 1907 reconciliation in an isolated hosted checkout."""
from pathlib import Path
import json
import subprocess

HEAD = 'b5e25076abc98c6a57f7078bdc335a5e916c5851'
DEV = '2ad1b0a952642e296c76a95d687962d0dccbf071'
BASE = '14738dc3de79881c549d8371e9933c08a92fda27'

def git(*args):
    return subprocess.check_output(['git', *args], text=True)

def original(ref, path):
    return git('show', ref + ':' + path)

def replace(source, before, after):
    assert source.count(before) == 1, (before, source.count(before))
    return source.replace(before, after)

assert git('rev-parse', 'HEAD').strip() == HEAD
assert git('merge-base', HEAD, DEV).strip() == BASE
expected = {
    '.github/workflows/developer-tools.yml',
    'tools/ci/contracts/workflows/developer-tools.yml/jobs/linux-portable.json',
    'apps/latentd/src/standalone/state/validation.rs',
    'contracts/dev/composition-support-v1.json',
    'tools/go_network_deadline_reference.py',
    'tools/tests/test_go_write_progress.py',
}
assert set(git('diff', '--name-only', '--diff-filter=U').splitlines()) == expected
# The independently implemented Rustup fix is identical except for comments and
# the local variable name. Keep development's matching workflow and contract.
for path in ('.github/workflows/developer-tools.yml',
             'tools/ci/contracts/workflows/developer-tools.yml/jobs/linux-portable.json'):
    Path(path).write_text(original(DEV, path))
# Development's scoped parser checks the complete read/write deadline block and
# the readiness projection; preserve the additional mutation controls too.
path = 'tools/go_network_deadline_reference.py'
Path(path).write_text(original(DEV, path))
path = 'tools/tests/test_go_write_progress.py'
s = original(DEV, path)
s = replace(s, "                             (deadline.MATERIALS[2],b'if !observation {'),",
    "                             (deadline.MATERIALS[2],b'now + Duration::from_millis(u64::from(value))'),\n"
    "                             (deadline.MATERIALS[2],b'if !observation {'),\n"
    "                             (deadline.MATERIALS[2],b'if !observation {\\n            if let Some(requested) = requested {'),")
Path(path).write_text(s)
# Preserve the closed inbox census, its final lifetime check and the original
# physical payload verifier. Both projections use the same complete scan.
path = 'apps/latentd/src/standalone/state/validation.rs'
s = original(HEAD, path)
d = original(DEV, path)
s = replace(s, 'validate_inventory_inner(view, identity, quotas, original, None)',
    'validate_inventory_inner(view, identity, quotas, original, None, &RejectPayloads)')
s = replace(s, '        Some((source, expected_before)),\n    )?',
    '        Some((source, expected_before)),\n        &RejectPayloads,\n    )?')
s = replace(s, '    )>,\n) -> Result<Option<latent_state::store_identity::InboxCustodyWatermark>, StoreError> {',
    '    )>,\n    payloads: &dyn PayloadVerifier,\n) -> Result<Option<latent_state::store_identity::InboxCustodyWatermark>, StoreError> {')
s = replace(s, '            reject_unverified_payload(key, bytes)?;',
    '            payloads.verify(view, key, bytes)?;')
start = d.index('#[cfg(target_os = "linux")]\npub(super) fn validate_with_local_payloads(')
end = d.index('fn validate_global_bootstrap(', start)
physical = d[start:end]
physical = replace(physical, '    validate_with_payloads(view, identity, quotas, original, payloads)',
    '    validate_inventory_with_local_payloads(view, identity, quotas, original, payloads).map(|_| ())')
wrapper = '''/// Return an inbox watermark only after the same physical payload checks.
#[cfg(target_os = "linux")]
pub(super) fn validate_inventory_with_local_payloads(
    view: &ReadView,
    identity: &StoreIdentity,
    quotas: &[TenantQuota],
    original: &NativeReservation,
    payloads: &LocalPayloadVerifier<'_>,
) -> Result<Option<latent_state::store_identity::InboxCustodyWatermark>, StoreError> {
    validate_inventory_inner(view, identity, quotas, original, None, payloads)
}

'''
s = replace(s, 'fn validate_global_bootstrap(', physical + wrapper + 'fn validate_global_bootstrap(')
s = replace(s, '// Standalone has not yet installed the same-root physical blob inventory at\n// startup. Logical closure alone cannot prove that required bytes exist.',
    '// Without an admitted same-root physical provider, logical closure alone\n// cannot prove that required payload bytes exist.')
Path(path).write_text(s)
# Keep the already-admitted blob owner for the subsequent protected inbox scan.
# Clone it only after the unique-owner durable promotion has completed.
path = 'apps/latentd/src/standalone/state/store.rs'
s = Path(path).read_text()
s = replace(s, 'pub(super) struct LocalPayloadSelection {\n',
    'pub(super) struct LocalPayloadSelection {\n    owner: Arc<latent_blobs::local::LocalBlobStore>,\n')
s = replace(s, 'impl LocalPayloadSelection {\n', '''impl LocalPayloadSelection {
    pub(super) fn inventory_payloads(
        &self,
    ) -> (Arc<latent_blobs::local::LocalBlobStore>, crate::config::ProviderIdentity) {
        (Arc::clone(&self.owner), self.provider.clone())
    }

''')
s = replace(s, '''        let selection = LocalPayloadSelection {
            provider: provider.clone(),
            namespace: owner.namespace().to_owned(),
            root,
            durable_retention,
        };''', '''        let selected_provider = provider.clone();
        let namespace = owner.namespace().to_owned();''')
s = replace(s, '        self.local_payload_selection = Some(Box::new(selection));', '''        self.local_payload_selection = Some(Box::new(LocalPayloadSelection {
            owner: Arc::clone(&owner),
            provider: selected_provider,
            namespace,
            root,
            durable_retention,
        }));''')
Path(path).write_text(s)
path = 'apps/latentd/src/standalone/state/kernel.rs'
s = Path(path).read_text()
s = replace(s, '        let inventory_original = bootstrap.original();', '''        let inventory_original = bootstrap.original();
        #[cfg(target_os = "linux")]
        let inventory_payloads = bootstrap
            .local_payload_selection
            .as_ref()
            .map(|selection| selection.inventory_payloads());''')
s = replace(s, '''            move |view| {
                super::validation::validate_inventory(''', '''            move |view| {
                #[cfg(target_os = "linux")]
                if let Some((owner, provider)) = inventory_payloads.as_ref() {
                    return super::validation::validate_inventory_with_local_payloads(
                        view,
                        &inventory_identity,
                        &inventory_quotas,
                        &inventory_original,
                        &super::validation::LocalPayloadVerifier {
                            store: owner,
                            provider,
                            original: &inventory_original,
                        },
                    );
                }
                super::validation::validate_inventory(''')
Path(path).write_text(s)
# Keep the branch's other provenance entries. Provider provenance is rebound to
# the actual merged source in a descendant commit after creating the merge.
path = 'contracts/dev/composition-support-v1.json'
Path(path).write_text(original(HEAD, path))
for path in expected:
    assert '<<<<<<< HEAD' not in Path(path).read_text()
subprocess.run(['git', 'add', '-u'], check=True)
assert not git('diff', '--name-only', '--diff-filter=U')
subprocess.run(['git', 'diff', '--cached', '--check'], check=True)
print('RECONCILED_ALL_SIX_CONFLICTS', flush=True)
