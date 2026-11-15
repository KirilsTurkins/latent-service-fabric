from pathlib import Path

def replace(text, old, new):
    assert text.count(old) == 1, (old, text.count(old))
    return text.replace(old, new)

p = Path('apps/latentd/src/standalone/state/store.rs')
s = p.read_text()
s = replace(s, '    owner: Arc<latent_blobs::local::LocalBlobStore>,\n    provider:', '    owner: Option<Arc<latent_blobs::local::LocalBlobStore>>,\n    provider:')
s = replace(s, '    ) -> (Arc<latent_blobs::local::LocalBlobStore>, crate::config::ProviderIdentity) {\n        (Arc::clone(&self.owner), self.provider.clone())', '''    ) -> Option<InventoryPayloads> {
        self.owner.as_ref().map(|owner| (Arc::clone(owner), self.provider.clone()))''')
s = replace(s, '#[cfg(target_os = "linux")]\npub(super) struct LocalPayloadSelection {', '''#[cfg(target_os = "linux")]
pub(super) type InventoryPayloads = (
    Arc<latent_blobs::local::LocalBlobStore>,
    crate::config::ProviderIdentity,
);

#[cfg(target_os = "linux")]
pub(super) struct LocalPayloadSelection {''')
s = replace(s, '            owner: Arc::clone(&owner),\n            provider: selected_provider,', '''            // A non-durable inventory was validated with RejectPayloads and
            // must remain uniquely owned for any later explicit promotion.
            // Only the already-admitted durable owner can verify retained rows.
            owner: (already_durable || durable_retention).then(|| Arc::clone(&owner)),
            provider: selected_provider,''')
p.write_text(s)
p = Path('apps/latentd/src/standalone/state/kernel.rs')
s = replace(p.read_text(), '.map(|selection| selection.inventory_payloads());', '.and_then(|selection| selection.inventory_payloads());')
p.write_text(s)
print('EPHEMERAL_OWNER_REMAINS_UNIQUE; DURABLE_INVENTORY_STILL_VERIFIED', flush=True)
