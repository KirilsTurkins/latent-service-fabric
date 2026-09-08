use latent_executor::{PreparationKey, PreparedComponent};

use crate::backend::PreparedRuntime;

impl super::PreparedCache<PreparedRuntime> {
    pub(crate) fn cached_preparation(&self, key: &PreparationKey) -> Option<PreparedComponent> {
        let state = self.lock();
        let mut found = None;
        for entry in state.entries.values() {
            let descriptor = entry.runtime.descriptor();
            if &descriptor.key == key {
                if found.is_some() {
                    return None;
                }
                found = Some(descriptor);
            }
        }
        found.cloned()
    }
}
