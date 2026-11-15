from pathlib import Path
import hashlib
import subprocess

HEAD = 'b5e25076abc98c6a57f7078bdc335a5e916c5851'
BASE = '35ab1b776df07f0fa1c1bb64d3699915afffb38b'
root = Path.cwd()
def git(*args):
    return subprocess.check_output(['git', *args])
def stage(number, name):
    return git('show', f':{number}:{name}').decode()
def replace(source, old, new):
    assert source.count(old) == 1, old
    return source.replace(old, new)
def save(name, source):
    (root / name).write_text(source)
assert git('rev-parse', 'HEAD').decode().strip() == HEAD
assert git('rev-parse', 'MERGE_HEAD').decode().strip() == BASE
expected = ['.github/workflows/developer-tools.yml', 'apps/latentd/src/standalone/state/validation.rs', 'contracts/dev/composition-support-v1.json', 'tools/ci/contracts/workflows/developer-tools.yml/jobs/linux-portable.json', 'tools/go_network_deadline_reference.py', 'tools/tests/test_go_write_progress.py']
assert git('diff', '--name-only', '--diff-filter=U').decode().splitlines() == expected
for name in (expected[0], expected[3]):
    save(name, stage(3, name))
name = expected[4]
s = stage(2, name)
needle = "                (facade, b'r := raw.ConnectContext(ctx, request)'),"
save(name, replace(s, needle, "                (connection, b'observation_deadline: if observation { requested } else { None }'),\n" + needle))
name = expected[5]
s = stage(2, name)
needle = "                             (deadline.MATERIALS[3],b'r := raw.ConnectContext(ctx, request)')):"
save(name, replace(s, needle, "                             (deadline.MATERIALS[2],b'observation_deadline: if observation { requested } else { None }'),\n" + needle))
name = expected[1]
s = stage(2, name)
theirs = stage(3, name)
s = replace(s, 'validate_inventory_inner(view, identity, quotas, original, None)', 'validate_inventory_inner(view, identity, quotas, original, None, &RejectPayloads)')
s = replace(s, '        Some((source, expected_before)),\n', '        Some((source, expected_before)),\n        &RejectPayloads,\n')
s = replace(s, '    )>,\n) -> Result<Option<latent_state::store_identity::InboxCustodyWatermark>, StoreError> {', '    )>,\n    payloads: &dyn PayloadVerifier,\n) -> Result<Option<latent_state::store_identity::InboxCustodyWatermark>, StoreError> {')
s = replace(s, '            reject_unverified_payload(key, bytes)?;', '            payloads.verify(view, key, bytes)?;')
a = theirs.index('#[cfg(target_os = "linux")]\npub(super) fn validate_with_local_payloads(')
b = theirs.index('fn validate_global_bootstrap(', a)
extra = replace(theirs[a:b], '    validate_with_payloads(view, identity, quotas, original, payloads)', '    validate_inventory_with_local_payloads(view, identity, quotas, original, payloads).map(|_| ())')
extra += '''/// Recheck physical payload custody and the full inbox inventory on the same
/// coherent view before a protected checkpoint can accept that inventory.
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
s = replace(s, 'fn validate_global_bootstrap(', extra + 'fn validate_global_bootstrap(')
s = replace(s, '// Standalone has not yet installed the same-root physical blob inventory at\n// startup. Logical closure alone cannot prove that required bytes exist.', '// Without an installed same-root physical verifier, logical closure alone\n// cannot prove that required payload bytes exist.')
save(name, s)
name = 'apps/latentd/src/standalone/state/store.rs'
s = (root / name).read_text()
s = replace(s, '    durable_retention: bool,\n}\n\n#[cfg(target_os = "linux")]\nimpl LocalPayloadSelection', '    durable_retention: bool,\n    owner: std::sync::Weak<latent_blobs::local::LocalBlobStore>,\n}\n\n#[cfg(target_os = "linux")]\nimpl LocalPayloadSelection')
s = replace(s, 'impl LocalPayloadSelection {\n', '''impl LocalPayloadSelection {
    /// Borrow the actual installed owner for this complete scan. A lost owner
    /// is not permission to downgrade to a logical-only inventory check.
    pub(super) fn validate_inventory(
        &self,
        view: &latent_state::embedded::ReadView,
        identity: &latent_state::store_identity::StoreIdentity,
        quotas: &[latent_state::tenant::TenantQuota],
        original: &latent_core::native_capacity::NativeReservation,
    ) -> Result<Option<latent_state::store_identity::InboxCustodyWatermark>, StoreError> {
        let owner = self.owner.upgrade().ok_or(StoreError::Unavailable)?;
        validation::validate_inventory_with_local_payloads(
            view,
            identity,
            quotas,
            original,
            &validation::LocalPayloadVerifier {
                store: &owner,
                provider: &self.provider,
                original,
            },
        )
    }

''')
s = replace(s, '        let selection = LocalPayloadSelection {', '        let mut selection = LocalPayloadSelection {')
s = replace(s, '            durable_retention,\n        };', '            durable_retention,\n            owner: std::sync::Weak::new(),\n        };')
s = replace(s, '        self.local_payload_selection = Some(Box::new(selection));', '''        // Only create a weak projection after binding/promotion has finished;
        // those transitions require exclusive ownership of the original Arc.
        selection.owner = Arc::downgrade(&owner);
        self.local_payload_selection = Some(Arc::new(selection));''')
save(name, s)
name = 'apps/latentd/src/standalone/state/bootstrap.rs'
save(name, replace((root / name).read_text(), 'Option<Box<super::store::LocalPayloadSelection>>', 'Option<Arc<super::store::LocalPayloadSelection>>'))
name = 'apps/latentd/src/standalone/state/kernel.rs'
s = (root / name).read_text()
s = replace(s, '        let inventory_original = bootstrap.original();\n', '        let inventory_original = bootstrap.original();\n        #[cfg(target_os = "linux")]\n        let inventory_payloads = bootstrap.local_payload_selection.clone();\n')
s = replace(s, '            move |view| {\n                super::validation::validate_inventory(', '''            move |view| {
                #[cfg(target_os = "linux")]
                if let Some(payloads) = &inventory_payloads {
                    return payloads.validate_inventory(
                        view,
                        &inventory_identity,
                        &inventory_quotas,
                        &inventory_original,
                    );
                }
                super::validation::validate_inventory(''')
save(name, s)
name = expected[2]
s = stage(3, name)
s = replace(s, 'sha256:1f1e2da82d5cb855ec297f70171ef8b63f2ad331920a2f053a18c9daaf5120d6', 'sha256:' + hashlib.sha256((root / 'apps/latentd/src/config/providers.rs').read_bytes()).hexdigest())
save(name, s)
name = 'apps/latentd/src/standalone/state/store/tests.rs'
s = (root / name).read_text()
s = replace(s, '    let state = Arc::clone(bootstrap.opened_store.as_ref().unwrap());\n    let (references, state_link, stored_value, owner_count, effect_value, effect_disposition) =', '''    let state = Arc::clone(bootstrap.opened_store.as_ref().unwrap());
    // The checkpoint's second closed scan must preserve both physical payload
    // verification and inbox custody; falling back to RejectPayloads loses
    // otherwise valid durable recovery after the initializer has succeeded.
    let selection = Arc::clone(bootstrap.local_payload_selection.as_ref().unwrap());
    let inventory_identity = settings.store_identity.clone();
    let inventory_quotas = validation::quotas(&settings);
    let original = bootstrap.original();
    let verify = Arc::clone(&selection);
    let retained = Arc::clone(&original);
    let custody = state
        .with_store_retaining(StoreIoKind::Read, 0, original, move |engine| {
            let view = engine.snapshot()?;
            assert_eq!(
                validation::validate_inventory(
                    &view,
                    &inventory_identity,
                    &inventory_quotas,
                    &retained,
                ),
                Err(StoreError::UnsupportedFormat)
            );
            verify.validate_inventory(&view, &inventory_identity, &inventory_quotas, &retained)
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    assert_eq!(custody, None);
    let (references, state_link, stored_value, owner_count, effect_value, effect_disposition) =''')
s = replace(s, '    assert_eq!(&bytes, b"body");\n    drop(reader);\n    drop(owner);\n    state.close();', '''    assert_eq!(&bytes, b"body");
    drop(reader);
    drop(owner);
    // The projection is non-owning: it cannot keep an abandoned provider alive
    // or silently replace missing physical custody with logical-only scanning.
    assert!(selection.owner.upgrade().is_none());
    let inventory_identity = settings.store_identity.clone();
    let inventory_quotas = validation::quotas(&settings);
    let original = bootstrap.original();
    let retained = Arc::clone(&original);
    let refused = state
        .with_store_retaining(StoreIoKind::Read, 0, original, move |engine| {
            selection.validate_inventory(
                &engine.snapshot()?,
                &inventory_identity,
                &inventory_quotas,
                &retained,
            )
        })
        .unwrap()
        .await
        .unwrap();
    assert_eq!(refused, Err(StoreError::Unavailable));
    state.close();''')
save(name, s)
subprocess.run(['git', 'add', '-u'], check=True)
assert not git('ls-files', '-u')
subprocess.run(['git', 'diff', '--cached', '--check'], check=True)
print('RESOLVED_TREE=' + git('write-tree').decode().strip(), flush=True)
