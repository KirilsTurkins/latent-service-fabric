//! Activation-bound owners. Drop releases access; the host alone may commit.
//!
//! Errors remain exact WIT data. No denial becomes absence, no conflict retries,
//! and dropping an import future starts no detached cleanup or replacement work.
use std::marker::PhantomData;

use crate::bindings::state as raw;
pub use raw::{
    CommandInfo, Entry, PageInfo, StateError, Value, Version, VersionedValue, ViewIdentity,
};

#[must_use = "retain the activation's admitted command owner until calls retire"]
pub struct Command(raw::Transaction);

impl Command {
    pub fn acquire() -> Result<Self, StateError> {
        raw::acquire_command().map(Self)
    }

    pub fn info(&self) -> Result<CommandInfo, StateError> {
        raw::info(&self.0)
    }

    pub async fn get(&mut self, key: Vec<u8>) -> Result<Option<VersionedValue>, StateError> {
        raw::get(&self.0, key).await
    }

    pub async fn put(&mut self, key: Vec<u8>, value: Value) -> Result<(), StateError> {
        raw::put(&self.0, key, value).await
    }

    pub async fn delete(&mut self, key: Vec<u8>) -> Result<(), StateError> {
        raw::delete(&self.0, key).await
    }

    pub async fn scan(
        &mut self,
        prefix: Vec<u8>,
        limit: u32,
        cursor: Option<Vec<u8>>,
    ) -> Result<Page<'_>, StateError> {
        raw::scan(&self.0, prefix, limit, cursor)
            .await
            .map(Page::new)
    }

    /// Releases access only. Accepted work and abandoned staging remain host-owned.
    pub fn close(self) {
        drop(self);
    }

    pub(crate) fn borrow(&mut self) -> &raw::Transaction {
        &self.0
    }
}

/// Fresh read-only access has no mutation, intent staging or command key API.
#[must_use = "retain the selected fresh view until its calls and pages retire"]
pub struct Query(raw::QueryView);

impl Query {
    pub fn acquire() -> Result<Self, StateError> {
        raw::acquire_query().map(Self)
    }

    pub fn info(&self) -> Result<ViewIdentity, StateError> {
        raw::query_info(&self.0)
    }

    pub async fn get(&mut self, key: Vec<u8>) -> Result<Option<VersionedValue>, StateError> {
        raw::get_query(&self.0, key).await
    }

    pub async fn scan(
        &mut self,
        prefix: Vec<u8>,
        limit: u32,
        cursor: Option<Vec<u8>>,
    ) -> Result<Page<'_>, StateError> {
        raw::scan_query(&self.0, prefix, limit, cursor)
            .await
            .map(Page::new)
    }

    pub fn close(self) {
        drop(self);
    }
}

/// Bounded page data remains tied to its original command/query borrow.
#[must_use = "release the bounded page before closing its original view"]
pub struct Page<'view> {
    raw: raw::Page,
    view: PhantomData<&'view mut ()>,
}

impl<'view> Page<'view> {
    fn new(raw: raw::Page) -> Self {
        Self {
            raw,
            view: PhantomData,
        }
    }

    pub fn info(&self) -> Result<PageInfo, StateError> {
        raw::describe_page(&self.raw)
    }

    pub async fn next(&mut self) -> Result<Option<Entry>, StateError> {
        raw::page_next(&self.raw).await
    }

    pub fn close(self) {
        drop(self);
    }
}
