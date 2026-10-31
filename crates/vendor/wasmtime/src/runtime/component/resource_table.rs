use super::Resource;
use crate::prelude::*;
use crate::runtime::native_memory::{self, Memory, NativeVec};
use alloc::collections::{BTreeMap, BTreeSet};
use core::any::Any;
use core::fmt;
use core::mem;
use core::ops::{Deref, DerefMut};

#[derive(Debug)]
/// Errors returned by operations on `ResourceTable`
pub enum ResourceTableError {
    /// ResourceTable has no free keys
    Full,
    /// Resource not present in table
    NotPresent,
    /// Resource present in table, but with a different type
    WrongType,
    /// Resource cannot be deleted because child resources exist in the table. Consult wit docs for
    /// the particular resource to see which methods may return child resources.
    HasChildren,
    /// The original native allocation factory refused backing before allocation.
    Allocation(Error),
}

impl fmt::Display for ResourceTableError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Full => write!(f, "resource table has no free keys"),
            Self::NotPresent => write!(f, "resource not present"),
            Self::WrongType => write!(f, "resource is of another type"),
            Self::HasChildren => write!(f, "resource has children"),
            Self::Allocation(error) => write!(f, "resource allocation refused: {error}"),
        }
    }
}

impl core::error::Error for ResourceTableError {
    fn source(&self) -> Option<&(dyn core::error::Error + 'static)> {
        match self {
            Self::Allocation(error) => Some(error.as_ref()),
            _ => None,
        }
    }
}

/// The `ResourceTable` type maps a `Resource<T>` to its `T`.
pub struct ResourceTable {
    entries: EntryStorage,
    memory: Memory,
    free_head: Option<usize>,
    max_capacity: usize,
}

// The paid branch exposes only a slice: no caller can grow or detach its Vec.
// The legacy branch retains the original Vec allocation behavior.
#[derive(Debug)]
enum EntryStorage {
    Legacy(Vec<Entry>),
    Accounted(NativeVec<Entry>),
}
impl Deref for EntryStorage {
    type Target = [Entry];
    fn deref(&self) -> &[Entry] {
        match self {
            Self::Legacy(entries) => entries,
            Self::Accounted(entries) => entries,
        }
    }
}
impl DerefMut for EntryStorage {
    fn deref_mut(&mut self) -> &mut [Entry] {
        match self {
            Self::Legacy(entries) => entries,
            Self::Accounted(entries) => entries,
        }
    }
}
impl EntryStorage {
    fn push(&mut self, entry: Entry) -> Result<(), ResourceTableError> {
        match self {
            Self::Legacy(entries) => {
                entries.push(entry);
                Ok(())
            }
            Self::Accounted(entries) => entries.push(entry).map_err(ResourceTableError::Allocation),
        }
    }
}

// The Box is the first field, so even destructor unwind destroys/deallocates it
// before the separate original ticket. Typed delete moves out of the sole Box,
// physically freeing its backing before refund; the returned T owns no Box here.
struct ResourceValue {
    value: Box<dyn Any + Send>,
    allocation: Option<Box<dyn crate::NativeAllocation>>,
}
impl ResourceValue {
    fn new<T: Any + Send>(value: T, memory: &Memory) -> Result<Self, ResourceTableError> {
        let mut allocation = native_memory::reserve(memory, size_of::<T>())
            .map_err(ResourceTableError::Allocation)?;
        // Keep the pending ticket outside the Box until confirmation returns.
        // If allocated() unwinds, this later local deallocates before the ticket.
        let value = Box::new(value);
        if let Some(allocation) = allocation.as_mut() {
            allocation.allocated();
        }
        Ok(Self { value, allocation })
    }
    fn into_typed<T: Any>(self) -> Result<T, ResourceTableError> {
        let Self { value, allocation } = self;
        let result = match value.downcast::<T>() {
            Ok(value) => Ok(*value),
            Err(value) => {
                drop(value);
                Err(ResourceTableError::WrongType)
            }
        };
        drop(allocation);
        result
    }
    fn as_ref(&self) -> &(dyn Any + Send) {
        self.value.as_ref()
    }
    fn as_mut(&mut self) -> &mut (dyn Any + Send) {
        self.value.as_mut()
    }
}
impl Deref for ResourceValue {
    type Target = dyn Any + Send;
    fn deref(&self) -> &Self::Target {
        self.as_ref()
    }
}
impl DerefMut for ResourceValue {
    fn deref_mut(&mut self) -> &mut Self::Target {
        self.as_mut()
    }
}
impl fmt::Debug for ResourceValue {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.value.fmt(f)
    }
}

#[derive(Debug)]
enum Children {
    Legacy(BTreeSet<u32>),
    Accounted(NativeVec<u32>),
}
impl Children {
    fn new(memory: Memory) -> Self {
        match memory {
            None => Self::Legacy(BTreeSet::new()),
            // NativeVec's exact zero-capacity constructor neither reserves nor
            // allocates: checked Layout::array::<u32>(0) has zero size.
            memory => Self::Accounted(
                NativeVec::with_capacity(0, memory)
                    .expect("zero-capacity children cannot allocate"),
            ),
        }
    }
    fn is_empty(&self) -> bool {
        match self {
            Self::Legacy(values) => values.is_empty(),
            Self::Accounted(values) => values.is_empty(),
        }
    }
    fn contains(&self, child: &u32) -> bool {
        match self {
            Self::Legacy(values) => values.contains(child),
            Self::Accounted(values) => values.binary_search(child).is_ok(),
        }
    }
    fn prepare_add(&self) -> Result<Option<NativeVec<u32>>, ResourceTableError> {
        match self {
            Self::Legacy(_) => Ok(None),
            Self::Accounted(values) => values
                .prepare_capacity(
                    values
                        .len()
                        .checked_add(1)
                        .ok_or(ResourceTableError::Full)?,
                )
                .map_err(ResourceTableError::Allocation),
        }
    }
    fn insert_prepared(&mut self, prepared: Option<NativeVec<u32>>, child: u32) {
        debug_assert!(!self.contains(&child));
        match self {
            Self::Legacy(values) => {
                assert!(prepared.is_none());
                values.insert(child);
            }
            Self::Accounted(values) => {
                values.commit_capacity(prepared);
                match values.binary_search(&child) {
                    Ok(_) => {}
                    Err(index) => values.insert_reserved(index, child),
                }
            }
        }
    }
    fn remove(&mut self, child: &u32) -> bool {
        match self {
            Self::Legacy(values) => values.remove(child),
            Self::Accounted(values) => {
                let found = values.binary_search(child).is_ok();
                if found {
                    values.retain_mut(|value| value != child);
                }
                found
            }
        }
    }
    fn iter(&self) -> ChildrenIter<'_> {
        match self {
            Self::Legacy(values) => ChildrenIter::Legacy(values.iter()),
            Self::Accounted(values) => ChildrenIter::Accounted(values.iter()),
        }
    }
}
enum ChildrenIter<'a> {
    Legacy(alloc::collections::btree_set::Iter<'a, u32>),
    Accounted(core::slice::Iter<'a, u32>),
}
impl<'a> Iterator for ChildrenIter<'a> {
    type Item = &'a u32;
    fn next(&mut self) -> Option<Self::Item> {
        match self {
            Self::Legacy(values) => values.next(),
            Self::Accounted(values) => values.next(),
        }
    }
}

#[derive(Debug)]
enum Entry {
    Free { next: Option<usize> },
    Occupied { entry: TableEntry },
}

impl Entry {
    pub fn occupied(&self) -> Option<&TableEntry> {
        match self {
            Self::Occupied { entry } => Some(entry),
            Self::Free { .. } => None,
        }
    }

    pub fn occupied_mut(&mut self) -> Option<&mut TableEntry> {
        match self {
            Self::Occupied { entry } => Some(entry),
            Self::Free { .. } => None,
        }
    }
}

struct Tombstone;

// Change this to `true` to assist with handle debugging in development if
// necessary.
const DELETE_WITH_TOMBSTONE: bool = false;

/// Default setting for `ResourceTable::max_capacity`, chosen to be high
/// enough that it doesn't need changing all that often but low enough that
/// exhausting it isn't a massive problem for the host.
const DEFAULT_MAX_CAPACITY: usize = 1_000_000;

/// This structure tracks parent and child relationships for a given table entry.
///
/// Parents and children are referred to by table index. We maintain the
/// following invariants:
/// * the parent must exist when adding a child.
/// * whenever a child is created, its index is added to children.
/// * whenever a child is deleted, its index is removed from children.
/// * an entry with children may not be deleted.
#[derive(Debug)]
struct TableEntry {
    /// The entry in the table, as a boxed dynamically-typed object
    entry: ResourceValue,
    /// The index of the parent of this entry, if it has one.
    parent: Option<u32>,
    /// The indices of any children of this entry.
    children: Children,
}

impl TableEntry {
    fn new(entry: ResourceValue, parent: Option<u32>, memory: Memory) -> Self {
        Self {
            entry,
            parent,
            children: Children::new(memory),
        }
    }
    fn add_child(&mut self, child: u32) -> Result<(), ResourceTableError> {
        let prepared = self.children.prepare_add()?;
        self.children.insert_prepared(prepared, child);
        Ok(())
    }
    fn remove_child(&mut self, child: u32) {
        let was_removed = self.children.remove(&child);
        debug_assert!(was_removed);
    }
}

impl ResourceTable {
    /// Create an empty table
    pub fn new() -> Self {
        ResourceTable::with_capacity(0)
    }

    /// Returns whether or not this table is empty.
    ///
    /// Note that this is an `O(n)` operation, where `n` is the number of
    /// entries in the backing `Vec`.
    pub fn is_empty(&self) -> bool {
        self.entries.iter().all(|entry| match entry {
            Entry::Free { .. } => true,
            Entry::Occupied { entry } => entry.entry.downcast_ref::<Tombstone>().is_some(),
        })
    }

    /// Returns the maximum capacity of this table, in elements, before adding
    /// any more will be refused.
    pub fn max_capacity(&self) -> usize {
        self.max_capacity
    }

    /// Configures the maximum number of entries that may be present within this
    /// table.
    ///
    /// Note that this does not retroactively shrink the table nor evict
    /// existing entries should the maximum be smaller than the current size of
    /// the entry table.
    pub fn set_max_capacity(&mut self, max: usize) {
        self.max_capacity = max;
    }

    /// Create an empty table with at least the specified capacity.
    pub fn with_capacity(capacity: usize) -> Self {
        ResourceTable {
            entries: EntryStorage::Legacy(Vec::with_capacity(capacity)),
            memory: None,
            free_head: None,
            max_capacity: DEFAULT_MAX_CAPACITY,
        }
    }

    /// Bind only an empty internal table to its original Store-selected factory.
    /// No existing resource or backing allocation is adopted after construction.
    pub(crate) fn with_native_memory(memory: Memory) -> Self {
        if memory.is_none() {
            return Self::new();
        }
        Self {
            entries: EntryStorage::Accounted(
                NativeVec::with_capacity(0, memory.clone())
                    .expect("zero-capacity table cannot allocate"),
            ),
            memory,
            free_head: None,
            max_capacity: DEFAULT_MAX_CAPACITY,
        }
    }

    /// Inserts a new value `T` into this table, returning a corresponding
    /// `Resource<T>` which can be used to refer to it after it was inserted.
    pub fn push<T>(&mut self, entry: T) -> Result<Resource<T>, ResourceTableError>
    where
        T: Send + 'static,
    {
        let value = ResourceValue::new(entry, &self.memory)?;
        let idx = self.push_(TableEntry::new(value, None, self.memory.clone()))?;
        Ok(Resource::new_own(idx))
    }

    /// Pop an index off of the free list, if it's not empty.
    fn pop_free_list(&mut self) -> Option<usize> {
        if let Some(ix) = self.free_head {
            // Advance free_head to the next entry if one is available.
            match &self.entries[ix] {
                Entry::Free { next } => self.free_head = *next,
                Entry::Occupied { .. } => unreachable!(),
            }
            Some(ix)
        } else {
            None
        }
    }

    /// Free an entry in the table, returning its [`TableEntry`]. Add the index to the free list.
    fn free_entry(&mut self, ix: usize, debug: bool) -> TableEntry {
        if debug {
            // Instead of making this entry available for reuse, we leave a
            // tombstone in debug mode.  This helps detect use-after-delete and
            // double-delete bugs.
            match mem::replace(
                &mut self.entries[ix],
                Entry::Occupied {
                    entry: TableEntry {
                        entry: ResourceValue {
                            value: Box::new(Tombstone),
                            allocation: None,
                        },
                        parent: None,
                        children: Children::new(self.memory.clone()),
                    },
                },
            ) {
                Entry::Occupied { entry } => entry,
                Entry::Free { .. } => unreachable!(),
            }
        } else {
            let entry = match core::mem::replace(
                &mut self.entries[ix],
                Entry::Free {
                    next: self.free_head,
                },
            ) {
                Entry::Occupied { entry } => entry,
                Entry::Free { .. } => unreachable!(),
            };

            self.free_head = Some(ix);

            entry
        }
    }

    /// Push a new entry into the table, returning its handle. This will prefer to use free entries
    /// if they exist, falling back on pushing new entries onto the end of the table.
    fn push_(&mut self, e: TableEntry) -> Result<u32, ResourceTableError> {
        if let Some(free) = self.pop_free_list() {
            self.entries[free] = Entry::Occupied { entry: e };
            Ok(free.try_into().unwrap())
        } else {
            if self.entries.len() >= self.max_capacity {
                return Err(ResourceTableError::Full);
            }
            let ix = self
                .entries
                .len()
                .try_into()
                .map_err(|_| ResourceTableError::Full)?;
            self.entries.push(Entry::Occupied { entry: e })?;
            Ok(ix)
        }
    }

    fn occupied(&self, key: u32) -> Result<&TableEntry, ResourceTableError> {
        self.entries
            .get(key as usize)
            .and_then(Entry::occupied)
            .ok_or(ResourceTableError::NotPresent)
    }

    fn occupied_mut(&mut self, key: u32) -> Result<&mut TableEntry, ResourceTableError> {
        self.entries
            .get_mut(key as usize)
            .and_then(Entry::occupied_mut)
            .ok_or(ResourceTableError::NotPresent)
    }

    /// Insert a resource at the next available index, and track that it has a
    /// parent resource.
    ///
    /// The parent must exist to create a child. All children resources must
    /// be destroyed before a parent can be destroyed - otherwise
    /// [`ResourceTable::delete`] will fail with
    /// [`ResourceTableError::HasChildren`].
    ///
    /// Parent-child relationships are tracked inside the table to ensure that
    /// a parent resource is not deleted while it has live children. This
    /// allows child resources to hold "references" to a parent by table
    /// index, to avoid needing e.g. an `Arc<Mutex<parent>>` and the associated
    /// locking overhead and design issues, such as child existence extending
    /// lifetime of parent referent even after parent resource is destroyed,
    /// possibility for deadlocks.
    pub fn push_child<T, U>(
        &mut self,
        entry: T,
        parent: &Resource<U>,
    ) -> Result<Resource<T>, ResourceTableError>
    where
        T: Send + 'static,
        U: 'static,
    {
        let parent = parent.rep();
        self.occupied(parent)?;
        // Stage the parent's complete child-index replacement before creating
        // or publishing the resource. A refusal leaves both relationships intact.
        let prepared = self.occupied(parent)?.children.prepare_add()?;
        let value = ResourceValue::new(entry, &self.memory)?;
        let child = self.push_(TableEntry::new(value, Some(parent), self.memory.clone()))?;
        self.occupied_mut(parent)?
            .children
            .insert_prepared(prepared, child);
        Ok(Resource::new_own(child))
    }

    /// Add an already-resident child to a resource.
    pub fn add_child<T: 'static, U: 'static>(
        &mut self,
        child: Resource<T>,
        parent: Resource<U>,
    ) -> Result<(), ResourceTableError> {
        if self.memory.is_none() {
            let entry = self.occupied_mut(child.rep())?;
            assert!(entry.parent.is_none());
            entry.parent = Some(parent.rep());
            self.occupied_mut(parent.rep())?.add_child(child.rep())?;
        } else {
            assert!(self.occupied(child.rep())?.parent.is_none());
            let prepared = self.occupied(parent.rep())?.children.prepare_add()?;
            self.occupied_mut(child.rep())?.parent = Some(parent.rep());
            self.occupied_mut(parent.rep())?
                .children
                .insert_prepared(prepared, child.rep());
        }
        Ok(())
    }

    /// Remove a child to from a resource (but leave it in the table).
    pub fn remove_child<T: 'static, U: 'static>(
        &mut self,
        child: Resource<T>,
        parent: Resource<U>,
    ) -> Result<(), ResourceTableError> {
        let entry = self.occupied_mut(child.rep())?;
        assert_eq!(entry.parent, Some(parent.rep()));
        entry.parent = None;
        self.occupied_mut(parent.rep())?.remove_child(child.rep());
        Ok(())
    }

    /// Get an immutable reference to a resource of a given type at a given
    /// index.
    ///
    /// Multiple shared references can be borrowed at any given time.
    pub fn get<T: Any + Sized>(&self, key: &Resource<T>) -> Result<&T, ResourceTableError> {
        self.get_(key.rep())?
            .downcast_ref()
            .ok_or(ResourceTableError::WrongType)
    }

    fn get_(&self, key: u32) -> Result<&dyn Any, ResourceTableError> {
        let r = self.occupied(key)?;
        Ok(&*r.entry)
    }

    /// Get an mutable reference to a resource of a given type at a given
    /// index.
    pub fn get_mut<T: Any + Sized>(
        &mut self,
        key: &Resource<T>,
    ) -> Result<&mut T, ResourceTableError> {
        self.get_any_mut(key.rep())?
            .downcast_mut()
            .ok_or(ResourceTableError::WrongType)
    }

    /// Returns the raw `Any` at the `key` index provided.
    pub fn get_any_mut(&mut self, key: u32) -> Result<&mut dyn Any, ResourceTableError> {
        let r = self.occupied_mut(key)?;
        Ok(&mut *r.entry)
    }

    /// Remove the specified entry from the table.
    pub fn delete<T>(&mut self, resource: Resource<T>) -> Result<T, ResourceTableError>
    where
        T: Any,
    {
        self.delete_maybe_debug(resource, DELETE_WITH_TOMBSTONE)
    }

    fn delete_maybe_debug<T>(
        &mut self,
        resource: Resource<T>,
        debug: bool,
    ) -> Result<T, ResourceTableError>
    where
        T: Any,
    {
        debug_assert!(resource.owned());
        let entry = self.delete_entry(resource.rep(), debug)?;
        entry.entry.into_typed()
    }

    fn delete_entry(&mut self, key: u32, debug: bool) -> Result<TableEntry, ResourceTableError> {
        if !self.occupied(key)?.children.is_empty() {
            return Err(ResourceTableError::HasChildren);
        }
        let e = self.free_entry(key as usize, debug);
        if let Some(parent) = e.parent {
            // Remove deleted resource from parent's child list.
            // Parent must still be present because it can't be deleted while still having
            // children:
            self.occupied_mut(parent)
                .expect("missing parent")
                .remove_child(key);
        }
        Ok(e)
    }

    /// Zip the values of the map with mutable references to table entries corresponding to each
    /// key. As the keys in the `BTreeMap` are unique, this iterator can give mutable references
    /// with the same lifetime as the mutable reference to the [ResourceTable].
    pub fn iter_entries<'a, T>(
        &'a mut self,
        map: BTreeMap<u32, T>,
    ) -> impl Iterator<Item = (Result<&'a mut dyn Any, ResourceTableError>, T)> {
        map.into_iter().map(move |(k, v)| {
            let item = self
                .occupied_mut(k)
                .map(|e| e.entry.as_mut())
                // Safety: extending the lifetime of the mutable reference.
                .map(|item| unsafe { &mut *(item as *mut dyn Any) });
            (item, v)
        })
    }

    /// Iterate over all children belonging to the provided parent
    pub fn iter_children<T>(
        &self,
        parent: &Resource<T>,
    ) -> Result<impl Iterator<Item = &(dyn Any + Send)> + use<'_, T>, ResourceTableError>
    where
        T: 'static,
    {
        let parent_entry = self.occupied(parent.rep())?;
        Ok(parent_entry.children.iter().map(|child_index| {
            let child = self.occupied(*child_index).expect("missing child");
            child.entry.as_ref()
        }))
    }

    /// Iterate over all the entries in this table.
    pub fn iter_mut(&mut self) -> impl Iterator<Item = &mut (dyn Any + Send)> {
        self.entries.iter_mut().filter_map(|entry| match entry {
            Entry::Occupied { entry } => Some(&mut *entry.entry),
            Entry::Free { .. } => None,
        })
    }
}

impl Default for ResourceTable {
    fn default() -> Self {
        ResourceTable::new()
    }
}

impl fmt::Debug for ResourceTable {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        write!(f, "[")?;
        let mut wrote = false;
        for (index, entry) in self.entries.iter().enumerate() {
            if let Entry::Occupied { entry } = entry {
                if entry.entry.downcast_ref::<Tombstone>().is_none() {
                    if wrote {
                        write!(f, ", ")?;
                    } else {
                        wrote = true;
                    }
                    write!(f, "{index}")?;
                }
            }
        }
        write!(f, "]")
    }
}

#[test]
pub fn test_free_list() {
    let mut table = ResourceTable::new();

    let x = table.push(()).unwrap();
    assert_eq!(x.rep(), 0);

    let y = table.push(()).unwrap();
    assert_eq!(y.rep(), 1);

    // Deleting x should put it on the free list, so the next entry should have the same rep.
    table.delete_maybe_debug(x, false).unwrap();
    let x = table.push(()).unwrap();
    assert_eq!(x.rep(), 0);

    // Deleting x and then y should yield indices 1 and then 0 for new entries.
    table.delete_maybe_debug(x, false).unwrap();
    table.delete_maybe_debug(y, false).unwrap();

    let y = table.push(()).unwrap();
    assert_eq!(y.rep(), 1);

    let x = table.push(()).unwrap();
    assert_eq!(x.rep(), 0);

    // As the free list is empty, this entry will have a new id.
    let x = table.push(()).unwrap();
    assert_eq!(x.rep(), 2);
}

#[test]
fn test_max_capacity() {
    let mut table = ResourceTable::new();
    assert_eq!(table.max_capacity(), DEFAULT_MAX_CAPACITY);

    table.set_max_capacity(0);
    assert_eq!(table.max_capacity(), 0);
    assert!(table.push(()).is_err());

    table.set_max_capacity(1);
    assert_eq!(table.max_capacity(), 1);
    let x = table.push(()).unwrap();
    assert!(table.push(()).is_err());

    table.set_max_capacity(0);
    assert!(table.push(()).is_err());
    table.delete(x).unwrap();
    let x = table.push(()).unwrap();
    table.delete(x).unwrap();

    table.set_max_capacity(10);

    let handles = (0..10).map(|_| table.push(()).unwrap()).collect::<Vec<_>>();
    assert!(table.push(()).is_err());
    for handle in handles {
        table.delete(handle).unwrap();
    }

    table.push(()).unwrap();
}

#[cfg(all(test, feature = "std", feature = "cranelift"))]
mod native_memory_tests {
    use super::*;
    use crate::{AsContextMut, Engine, NativeAllocation, NativeMemory, Store};
    use alloc::sync::Arc;
    use core::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
    use std::panic::{AssertUnwindSafe, catch_unwind};
    use std::sync::Mutex;

    #[derive(Default)]
    struct State {
        requests: Mutex<Vec<usize>>,
        retired: Mutex<Vec<usize>>,
        issued: AtomicUsize,
        active: AtomicUsize,
        confirmations: AtomicUsize,
        drops: AtomicUsize,
        deny_request: AtomicUsize,
        confirmation_panic: AtomicBool,
    }
    struct TestMemory(Arc<State>);
    struct Allocation {
        state: Arc<State>,
        id: usize,
    }
    impl NativeAllocation for Allocation {
        fn allocated(&mut self) {
            self.state.confirmations.fetch_add(1, Ordering::SeqCst);
            assert!(
                !self.state.confirmation_panic.load(Ordering::SeqCst),
                "resource-confirmation-unwind"
            );
        }
    }
    impl Drop for Allocation {
        fn drop(&mut self) {
            self.state.retired.lock().unwrap().push(self.id);
            self.state.active.fetch_sub(1, Ordering::SeqCst);
        }
    }
    #[derive(Debug)]
    struct Denied;
    impl fmt::Display for Denied {
        fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
            f.write_str("resource-original-Store-admission")
        }
    }
    impl std::error::Error for Denied {}
    impl NativeMemory for TestMemory {
        fn reserve(&self, bytes: usize) -> crate::Result<Box<dyn NativeAllocation>> {
            let mut requests = self.0.requests.lock().unwrap();
            requests.push(bytes);
            if requests.len() == self.0.deny_request.load(Ordering::SeqCst) {
                return Err(Error::new(Denied));
            }
            let id = self.0.issued.fetch_add(1, Ordering::SeqCst) + 1;
            self.0.active.fetch_add(1, Ordering::SeqCst);
            Ok(Box::new(Allocation {
                state: self.0.clone(),
                id,
            }))
        }
    }
    fn original_table() -> (Store<()>, ResourceTable, Arc<State>) {
        let state = Arc::new(State::default());
        let mut store =
            Store::try_new_with_memory(&Engine::default(), (), Arc::new(TestMemory(state.clone())))
                .unwrap();
        let table = ResourceTable::with_native_memory(store.as_context_mut().0.native_memory());
        state.requests.lock().unwrap().clear();
        (store, table, state)
    }
    fn refused<T>(result: Result<T, ResourceTableError>) {
        match result {
            Err(ResourceTableError::Allocation(error)) => {
                assert!(error.downcast_ref::<Denied>().is_some())
            }
            _ => panic!("original allocation refusal was not retained"),
        }
    }
    struct Probe {
        state: Arc<State>,
        box_ticket: usize,
        panic: bool,
    }
    impl Drop for Probe {
        fn drop(&mut self) {
            if self.box_ticket != 0 {
                assert!(
                    !self
                        .state
                        .retired
                        .lock()
                        .unwrap()
                        .contains(&self.box_ticket),
                    "resource Box ticket retired before its value destructor"
                );
            }
            self.state.drops.fetch_add(1, Ordering::SeqCst);
            assert!(!self.panic, "resource-destructor-unwind");
        }
    }
    fn probe(state: &Arc<State>, panic: bool) -> Probe {
        Probe {
            state: state.clone(),
            box_ticket: state.issued.load(Ordering::SeqCst) + 1,
            panic,
        }
    }

    #[test]
    fn original_store_box_and_entry_refusals_leave_no_published_resource() {
        let (store, mut table, state) = original_table();
        let baseline = state.active.load(Ordering::SeqCst);
        let confirmations = state.confirmations.load(Ordering::SeqCst);
        state.deny_request.store(1, Ordering::SeqCst);
        refused(table.push(51u64));
        assert!(table.is_empty());
        assert_eq!(state.active.load(Ordering::SeqCst), baseline);
        assert_eq!(state.confirmations.load(Ordering::SeqCst), confirmations);
        assert_eq!(*state.requests.lock().unwrap(), [size_of::<u64>()]);
        state.requests.lock().unwrap().clear();
        state.deny_request.store(2, Ordering::SeqCst);
        refused(table.push(52u64));
        assert!(table.is_empty());
        assert_eq!(state.active.load(Ordering::SeqCst), baseline);
        assert_eq!(
            *state.requests.lock().unwrap(),
            [size_of::<u64>(), size_of::<Entry>()]
        );
        state.deny_request.store(0, Ordering::SeqCst);
        let resource = table.push(53u64).unwrap();
        assert_eq!(resource.rep(), 0);
        assert_eq!(*table.get(&resource).unwrap(), 53);
        assert_eq!(state.active.load(Ordering::SeqCst), baseline + 2);
        drop(table);
        assert_eq!(state.active.load(Ordering::SeqCst), baseline);
        drop(store);
        assert_eq!(state.active.load(Ordering::SeqCst), 0);
    }

    #[test]
    fn typed_and_wrong_type_delete_retire_only_physical_boxes() {
        let (store, mut table, state) = original_table();
        let resource = table.push(probe(&state, false)).unwrap();
        let mut value = table.delete(resource).unwrap();
        assert!(state.retired.lock().unwrap().contains(&value.box_ticket));
        value.box_ticket = 0; // T is now an unboxed returned value, not paid Box backing.
        let wrong = table.push(probe(&state, false)).unwrap();
        let key = wrong.rep();
        assert!(matches!(
            table.delete(Resource::<u64>::new_own(key)),
            Err(ResourceTableError::WrongType)
        ));
        assert!(matches!(
            table.get(&wrong),
            Err(ResourceTableError::NotPresent)
        ));
        assert_eq!(state.drops.load(Ordering::SeqCst), 1);
        drop(table);
        drop(store);
        assert_eq!(state.active.load(Ordering::SeqCst), 0);
        // This legitimate typed return outlives its table and Store without
        // retaining a nonexistent Box allocation or manufacturing a new Box.
        drop(value);
        assert_eq!(state.drops.load(Ordering::SeqCst), 2);
    }

    #[test]
    fn child_capacity_refusal_is_atomic_and_reused_indices_stay_sorted() {
        let (store, mut table, state) = original_table();
        let parent = table.push(99u64).unwrap();
        state.requests.lock().unwrap().clear();
        let active = state.active.load(Ordering::SeqCst);
        let confirmed = state.confirmations.load(Ordering::SeqCst);
        state.deny_request.store(1, Ordering::SeqCst);
        refused(table.push_child(3u32, &parent));
        assert_eq!(table.entries.len(), 1);
        assert_eq!(table.iter_children(&parent).unwrap().count(), 0);
        assert_eq!(state.active.load(Ordering::SeqCst), active);
        assert_eq!(state.confirmations.load(Ordering::SeqCst), confirmed);
        assert_eq!(*state.requests.lock().unwrap(), [size_of::<u32>()]);
        state.deny_request.store(0, Ordering::SeqCst);
        let first = table.push_child(3u32, &parent).unwrap();
        let second = table.push_child(5u32, &parent).unwrap();
        let resident = table.push(8u32).unwrap();
        state.requests.lock().unwrap().clear();
        state.deny_request.store(1, Ordering::SeqCst);
        refused(table.add_child(
            Resource::<u32>::new_own(resident.rep()),
            Resource::<u64>::new_own(parent.rep()),
        ));
        assert!(table.occupied(resident.rep()).unwrap().parent.is_none());
        assert_eq!(table.iter_children(&parent).unwrap().count(), 2);
        state.deny_request.store(0, Ordering::SeqCst);
        table
            .add_child(
                Resource::<u32>::new_own(resident.rep()),
                Resource::<u64>::new_own(parent.rep()),
            )
            .unwrap();
        assert!(matches!(
            table.delete(Resource::<u64>::new_own(parent.rep())),
            Err(ResourceTableError::HasChildren)
        ));
        let reused = second.rep();
        assert_eq!(table.delete(second).unwrap(), 5);
        let middle = table.push_child(7u32, &parent).unwrap();
        assert_eq!(middle.rep(), reused);
        let values = table
            .iter_children(&parent)
            .unwrap()
            .map(|value| *value.downcast_ref::<u32>().unwrap())
            .collect::<Vec<_>>();
        assert_eq!(values, [3, 7, 8]);
        table.delete(first).unwrap();
        table.delete(middle).unwrap();
        table.delete(resident).unwrap();
        assert_eq!(table.delete(parent).unwrap(), 99);
        drop(table);
        drop(store);
        assert_eq!(state.active.load(Ordering::SeqCst), 0);
    }

    #[test]
    fn confirmation_and_destructor_unwind_keep_original_owner_until_physical_drop() {
        let (store, mut table, state) = original_table();
        let baseline = state.active.load(Ordering::SeqCst);
        state.confirmation_panic.store(true, Ordering::SeqCst);
        assert!(catch_unwind(AssertUnwindSafe(|| table.push(probe(&state, false)))).is_err());
        state.confirmation_panic.store(false, Ordering::SeqCst);
        assert!(table.is_empty());
        assert_eq!(state.drops.load(Ordering::SeqCst), 1);
        assert_eq!(state.active.load(Ordering::SeqCst), baseline);
        table.push(probe(&state, true)).unwrap();
        // Each original ticket, including the table's metadata buffer, owns
        // its payer independently of the Store and releases after real cleanup.
        drop(store);
        assert!(catch_unwind(AssertUnwindSafe(|| drop(table))).is_err());
        assert_eq!(state.drops.load(Ordering::SeqCst), 2);
        assert_eq!(state.active.load(Ordering::SeqCst), 0);
        let mut legacy = ResourceTable::with_capacity(1);
        let zst = legacy.push(()).unwrap();
        assert_eq!(legacy.delete(zst).unwrap(), ());
        assert_eq!(state.active.load(Ordering::SeqCst), 0);
    }
}
