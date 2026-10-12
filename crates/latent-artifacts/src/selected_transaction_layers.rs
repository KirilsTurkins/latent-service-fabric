//! Exact selected asset subset. Component/evidence bytes are streamed, not copied.
pub struct SelectedTransactionLayers {
    pub(crate) manifest: Vec<u8>,
    pub(crate) configuration: Vec<u8>,
    pub(crate) layers: Vec<(String, Vec<u8>)>,
}
impl SelectedTransactionLayers {
    #[must_use]
    pub fn parts(&self) -> (&[u8], &[u8], &[(String, Vec<u8>)]) {
        (&self.manifest, &self.configuration, &self.layers)
    }
    pub(crate) fn retained_bytes(&self) -> usize {
        self.layers.iter().fold(
            std::mem::size_of::<Self>()
                + self.manifest.capacity()
                + self.configuration.capacity()
                + self.layers.capacity() * std::mem::size_of::<(String, Vec<u8>)>(),
            |used, (name, bytes)| used + name.capacity() + bytes.capacity(),
        )
    }
}
