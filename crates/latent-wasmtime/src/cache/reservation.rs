use super::*;

impl<T> PrepareReservation<T> {
    pub(crate) fn track_runtime(&mut self, runtime: &Arc<T>) -> Result<(), PlatformError>
    where
        T: TrackedPreparedValue,
    {
        if self.residency.is_some() {
            return Err(capacity_error());
        }
        // The sealed concrete getter executes before any accounting lock.
        let charge = runtime.runtime_charge();
        self.residency = Some(PreparedResidency::claim(
            runtime,
            charge,
            &self.cache.runtime_observer,
        )?);
        Ok(())
    }

    #[cfg(test)]
    pub(crate) fn publish(
        self,
        runtime: Arc<T>,
        compiled_image_bytes: usize,
    ) -> Result<(), PlatformError> {
        let metadata_bytes = self
            .cache
            .lock()
            .preparing
            .get(&self.handle)
            .expect("live preparation reservation")
            .metadata_bytes;
        self.publish_with_metadata(runtime, compiled_image_bytes, metadata_bytes)
    }

    /// Charges the discovered immutable metadata footprint while retaining the
    /// full reservation until compilation and validation have completed.
    pub(crate) fn publish_with_metadata(
        self,
        runtime: Arc<T>,
        compiled_image_bytes: usize,
        actual_metadata_bytes: usize,
    ) -> Result<(), PlatformError> {
        drop(self.publish_deferred(runtime, compiled_image_bytes, actual_metadata_bytes)?);
        Ok(())
    }

    /// Publication is atomic; caller destroys returned evictions outside its
    /// own registry lock as well as the cache lock.
    pub(crate) fn publish_deferred(
        mut self,
        runtime: Arc<T>,
        compiled_image_bytes: usize,
        actual_metadata_bytes: usize,
    ) -> Result<Vec<Arc<T>>, PlatformError> {
        if compiled_image_bytes > self.cache.limits.maximum_compiled_image_bytes {
            return Err(capacity_error());
        }
        let key: Arc<str> = Arc::from(self.handle.as_str());
        let mut evicted = Vec::new();
        let mut retired_tokens = Vec::new();
        {
            let mut state = self.cache.lock();
            let cost = *state
                .preparing
                .get(&self.handle)
                .expect("live preparation reservation");
            if actual_metadata_bytes > cost.metadata_bytes {
                return Err(capacity_error());
            }
            let limits = &self.cache.limits;
            state.entries.reserve_publication(limits.maximum_entries)?;
            let actual_cost = PreparedRuntimeCost {
                source_bytes: cost.source_bytes,
                metadata_bytes: actual_metadata_bytes,
                compiled_image_bytes,
            };
            if state.needs_eviction(*limits, actual_cost) {
                evicted
                    .try_reserve(state.entries.len())
                    .map_err(|_| capacity_error())?;
                retired_tokens
                    .try_reserve(state.entries.len())
                    .map_err(|_| capacity_error())?;
            }
            let mut ledger = self.cache.runtime_observer.lock();
            match (&self.residency, &ledger) {
                (Some(token), Some(ledger)) => token.validate(&runtime, actual_cost, ledger)?,
                (None, None) => {}
                _ => return Err(capacity_error()),
            }
            while state.needs_eviction(*limits, actual_cost) {
                let mut entry = state.entries.remove_oldest().expect("resident LRU entry");
                state.retire(&entry, ledger.as_mut());
                if let Some(token) = entry.residency.take() {
                    retired_tokens.push(token);
                }
                evicted.push(entry.runtime);
                state.evictions = state.evictions.saturating_add(1);
            }
            let residency = self.residency.take();
            if let Some(token) = &residency {
                token.admit(ledger.as_mut().expect("validated runtime ledger"));
            }
            state.source_bytes += cost.source_bytes;
            state.metadata_bytes += actual_metadata_bytes;
            state.compiled_image_bytes += compiled_image_bytes;
            state.entries.insert(
                key,
                Entry {
                    runtime,
                    source_bytes: cost.source_bytes,
                    metadata_bytes: actual_metadata_bytes,
                    compiled_image_bytes,
                    residency,
                },
            );
            state.finish_preparing(&self.handle);
            self.active = false;
        }
        drop(retired_tokens);
        Ok(evicted)
    }

    /// Rebind a pre-read reservation after fully verified metadata determines
    /// an untrusted source's ordinary cache identity, without a second slot.
    pub(crate) fn rekey(mut self, handle: String) -> Result<PrepareAccess<T>, PlatformError> {
        if handle.is_empty() || handle.len() > MAXIMUM_HANDLE_BYTES || self.residency.is_some() {
            return Err(capacity_error());
        }
        let mut state = self.cache.lock();
        if handle == self.handle {
            drop(state);
            return Ok(PrepareAccess::Compile(self));
        }
        if let Some(runtime) = state.get(&handle) {
            state.finish_preparing(&self.handle);
            self.active = false;
            return Ok(PrepareAccess::Hit(runtime));
        }
        if state.preparing.contains_key(&handle) {
            return Err(platform_error(
                PlatformErrorCode::Unavailable,
                "component preparation is already in progress",
                true,
            ));
        }
        let cost = state
            .preparing
            .remove(&self.handle)
            .expect("live preparation reservation");
        state.preparing.insert(handle.clone(), cost);
        self.handle = handle;
        drop(state);
        Ok(PrepareAccess::Compile(self))
    }
}

impl<T> State<T> {
    fn needs_eviction(&self, limits: CacheLimits, cost: PreparedRuntimeCost) -> bool {
        self.entries.len() >= limits.maximum_entries
            || cost.source_bytes > limits.maximum_source_bytes - self.source_bytes
            || cost.metadata_bytes > limits.maximum_metadata_bytes - self.metadata_bytes
            || cost.compiled_image_bytes
                > limits.maximum_compiled_image_bytes - self.compiled_image_bytes
    }
}

impl<T> Drop for PrepareReservation<T> {
    fn drop(&mut self) {
        if self.active {
            self.cache.lock().finish_preparing(&self.handle);
        }
    }
}
