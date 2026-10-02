use super::{key_value as wit, port};
use std::sync::Arc;

const PAGE_SLOTS: usize = 16;
const TOTAL_PAGES: usize = 32;
const PAGE_BYTES: usize = 4 * 1024 * 1024;

pub(super) struct PageSlot {
    pub page: port::Page,
    pub next: usize,
    pub bytes: usize,
    pub _retained: port::RetainedTransfer,
}
#[derive(Default)]
pub(crate) struct Access {
    pub(super) host: Option<Arc<dyn port::TransactionHost>>,
    command: bool,
    query: bool,
    pub(super) pages: Vec<Option<PageSlot>>,
    page_bytes: usize,
    pub(super) lowerings: Vec<port::RetainedTransfer>,
}
impl Access {
    pub(crate) fn attach(host: Arc<dyn port::TransactionHost>) -> Self {
        Self {
            host: Some(host),
            pages: Vec::with_capacity(TOTAL_PAGES),
            lowerings: Vec::with_capacity(256),
            ..Self::default()
        }
    }
    pub(super) fn host(&self) -> Result<Arc<dyn port::TransactionHost>, wit::StateError> {
        self.host
            .as_ref()
            .cloned()
            .ok_or(wit::StateError::PermissionDenied)
    }
    pub(super) fn acquire(&mut self, mode: port::Mode) -> Result<u32, wit::StateError> {
        let host = self.host()?;
        host.acquire(mode).map_err(super::convert::state_error)?;
        match mode {
            port::Mode::Command => {
                self.command = true;
                Ok(0)
            }
            port::Mode::Query => {
                self.query = true;
                Ok(1)
            }
        }
    }
    pub(super) fn selected(
        &self,
        mode: port::Mode,
        representation: u32,
    ) -> Result<Arc<dyn port::TransactionHost>, wit::StateError> {
        let live = match mode {
            port::Mode::Command => self.command && representation == 0,
            port::Mode::Query => self.query && representation == 1,
        };
        if !live {
            return Err(wit::StateError::HandleClosed);
        }
        let host = self.host()?;
        if host.mode() != mode {
            return Err(wit::StateError::WrongMode);
        }
        host.authorize_read().map_err(super::convert::state_error)?;
        Ok(host)
    }
    pub(super) fn release(&mut self, mode: port::Mode, representation: u32) {
        let valid = match mode {
            port::Mode::Command => self.command && representation == 0,
            port::Mode::Query => self.query && representation == 1,
        };
        if valid {
            match mode {
                port::Mode::Command => self.command = false,
                port::Mode::Query => self.query = false,
            }
            if let Some(host) = &self.host {
                host.release(mode);
            }
        }
    }
    pub(super) fn reserve_lowering(
        &mut self,
        host: &dyn port::TransactionHost,
        bytes: usize,
    ) -> Result<(), wit::StateError> {
        if self.lowerings.len() >= 256 {
            return Err(wit::StateError::ReadBudgetExhausted);
        }
        self.lowerings.push(
            host.retain_transfer(bytes)
                .map_err(super::convert::state_error)?,
        );
        Ok(())
    }
    pub(super) fn insert_page(
        &mut self,
        host: &dyn port::TransactionHost,
        page: port::Page,
    ) -> Result<u32, wit::StateError> {
        let bytes = super::convert::page_size(&page)?;
        if self.pages.len() >= TOTAL_PAGES
            || self.pages.iter().flatten().count() >= PAGE_SLOTS
            || bytes > PAGE_BYTES.saturating_sub(self.page_bytes)
        {
            return Err(wit::StateError::ReadBudgetExhausted);
        }
        let retained = host
            .retain_transfer(bytes)
            .map_err(super::convert::state_error)?;
        let id = u32::try_from(self.pages.len() + 2)
            .map_err(|_| wit::StateError::ReadBudgetExhausted)?;
        self.page_bytes += bytes;
        self.pages.push(Some(PageSlot {
            page,
            next: 0,
            bytes,
            _retained: retained,
        }));
        Ok(id)
    }
    pub(super) fn page(&mut self, representation: u32) -> Result<&mut PageSlot, wit::StateError> {
        let index = representation
            .checked_sub(2)
            .ok_or(wit::StateError::HandleClosed)? as usize;
        self.pages
            .get_mut(index)
            .and_then(Option::as_mut)
            .ok_or(wit::StateError::HandleClosed)
    }
    pub(super) fn release_page(&mut self, representation: u32) {
        if let Some(slot) = representation
            .checked_sub(2)
            .and_then(|i| self.pages.get_mut(i as usize))
        {
            if let Some(page) = slot.take() {
                self.page_bytes -= page.bytes;
            }
        }
    }
}
impl Drop for Access {
    fn drop(&mut self) {
        self.pages.clear();
        self.lowerings.clear();
        if let Some(host) = &self.host {
            if self.command {
                host.release(port::Mode::Command);
            }
            if self.query {
                host.release(port::Mode::Query);
            }
            host.finish_guest_access();
        }
    }
}
