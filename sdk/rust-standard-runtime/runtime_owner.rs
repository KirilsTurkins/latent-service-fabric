// SPDX-License-Identifier: MIT OR Apache-2.0
//! Original-ledger admission and affine System backing for the selected PAL.
//!
//! No owner is a byte quota: the original Wasm memory bound still pays all
//! linear bytes. A Native owner follows a real infrastructure allocation;
//! moved user values and original mpsc/Arc backing retain their normal memory
//! charge. No registry borrow may span any of these broker operations.
use crate::alloc::{GlobalAlloc, Layout, System};
use crate::mem::ManuallyDrop;
use crate::ptr::{self, NonNull};

#[repr(C)]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct Token {
    pub(crate) generation: u64,
    pub(crate) id: u64,
}
impl Token {
    pub(crate) fn valid(self) -> bool {
        self.generation != 0 && self.id != 0
    }
}
#[repr(u32)]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Kind {
    Task = 0,
    ManagedIdleWorker = 1,
    Executor = 2,
    QueuedWork = 3,
    Wait = 4,
    Timer = 5,
    Result = 6,
    Native = 7,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Error {
    Unavailable,
    PermissionDenied,
    ResourceExhausted,
    Cancelled,
    Deadline,
    InvalidState,
    InvalidToken,
}
pub(crate) fn error(value: u8) -> Error {
    match value {
        0 => Error::Unavailable,
        1 => Error::PermissionDenied,
        2 => Error::ResourceExhausted,
        3 => Error::Cancelled,
        4 => Error::Deadline,
        5 => Error::InvalidState,
        6 => Error::InvalidToken,
        _ => panic!("invalid original runtime error discriminant"),
    }
}
// Borrow the original Task identity without manufacturing a second affine
// owner. The selected TLS backend retains this Task through actual frame exit.
pub(crate) fn park_task(token: Token) -> Result<(), Error> {
    assert!(token.valid(), "park requires the actual live Task token");
    operation(token, park)
}
pub(crate) fn wake_task(token: Token) -> Result<(), Error> {
    assert!(token.valid(), "wake requires the actual live Task token");
    operation(token, wake)
}
#[repr(C, align(8))]
struct RegisterResult([u8; 24]);

#[must_use = "a live logical owner must remain with its accepted work"]
pub(crate) struct Owner(Token);
impl Owner {
    pub(crate) fn admit(kind: Kind, parent: Option<Token>) -> Result<Self, Error> {
        if parent.is_some_and(|token| !token.valid()) {
            return Err(Error::InvalidToken);
        }
        let token = parent.unwrap_or(Token {
            generation: 0,
            id: 0,
        });
        let mut result = RegisterResult([0xff; 24]);
        unsafe {
            register(
                kind as u32,
                parent.is_some() as u32,
                token.generation,
                token.id,
                result.0.as_mut_ptr(),
            );
        }
        match result.0[0] {
            0 => {
                let token = Token {
                    generation: u64::from_le_bytes(result.0[8..16].try_into().unwrap()),
                    id: u64::from_le_bytes(result.0[16..24].try_into().unwrap()),
                };
                assert!(token.valid(), "invalid original runtime owner token");
                Ok(Self(token))
            }
            1 => Err(error(result.0[8])),
            _ => panic!("invalid original runtime register result"),
        }
    }
    pub(crate) fn token(&self) -> Token {
        self.0
    }
    pub(crate) fn park(&self) -> Result<(), Error> {
        operation(self.0, park)
    }
    pub(crate) fn wake(&self) -> Result<(), Error> {
        operation(self.0, wake)
    }
}
fn operation(token: Token, call: unsafe extern "C" fn(u64, u64, *mut u8)) -> Result<(), Error> {
    let mut result = [0xff; 2];
    unsafe {
        call(token.generation, token.id, result.as_mut_ptr());
    }
    match result[0] {
        0 => Ok(()),
        1 => Err(error(result[1])),
        _ => panic!("invalid original runtime operation result"),
    }
}
impl Drop for Owner {
    fn drop(&mut self) {
        assert!(
            operation(self.0, settle).is_ok(),
            "original runtime settlement rejected"
        );
    }
}

#[derive(Debug, PartialEq, Eq)]
pub(crate) enum AllocationError {
    Admission(Error),
    Allocation,
}

/// A single nonempty System allocation, admitted before allocation/publishing.
/// The Native lease is not permission to refund still-owned Wasm bytes.
/// Selected panic=abort semantics do not turn a panicking T destructor into a
/// successful free. ManuallyDrop also prevents that refund in source controls.
#[repr(C)]
struct SystemAllocation<T> {
    owner: ManuallyDrop<Owner>,
    value: ManuallyDrop<T>,
}
pub(crate) struct SystemOwned<T> {
    pointer: NonNull<SystemAllocation<T>>,
}
unsafe impl<T: Send> Send for SystemOwned<T> {}
unsafe impl<T: Sync> Sync for SystemOwned<T> {}
impl<T> SystemOwned<T> {
    pub(crate) fn try_new(value: T, parent: Option<Token>) -> Result<Self, AllocationError> {
        assert!(
            Layout::new::<T>().size() != 0,
            "System infrastructure backing must be nonempty"
        );
        let owner = Owner::admit(Kind::Native, parent).map_err(AllocationError::Admission)?;
        let layout = Layout::new::<SystemAllocation<T>>();
        let pointer = unsafe { System.alloc(layout) }.cast::<SystemAllocation<T>>();
        let Some(pointer) = NonNull::new(pointer) else {
            // No allocation was installed. Actual admission is rolled back,
            // while the caller's already constructed value keeps normal Drop.
            return Err(AllocationError::Allocation);
        };
        unsafe {
            pointer.as_ptr().write(SystemAllocation {
                owner: ManuallyDrop::new(owner),
                value: ManuallyDrop::new(value),
            });
        }
        Ok(Self { pointer })
    }
    pub(crate) fn pointer(&self) -> NonNull<T> {
        // addr_of_mut creates no reference to a value whose owner may be held
        // in an activation-local intrusive node rather than a Rust borrow.
        unsafe { NonNull::new_unchecked(ptr::addr_of_mut!((*self.pointer.as_ptr()).value).cast()) }
    }
    pub(crate) fn token(&self) -> Token {
        unsafe { (*self.pointer.as_ptr()).owner.token() }
    }
    /// Transfer the ONE allocation/Native owner to an intrusive runtime node.
    /// No drop, free or logical settlement is performed by this transfer.
    pub(crate) fn into_raw(self) -> NonNull<T> {
        ManuallyDrop::new(self).pointer()
    }
    /// # Safety
    /// `pointer` is the exact live pointer from into_raw for this same T. The
    /// caller has removed all registry/queue references and owns its unique
    /// recovery. No copied pointer or old generation may recover it twice.
    pub(crate) unsafe fn from_raw(pointer: NonNull<T>) -> Self {
        let pointer = unsafe {
            pointer
                .as_ptr()
                .cast::<u8>()
                .sub(crate::mem::offset_of!(SystemAllocation<T>, value))
                .cast::<SystemAllocation<T>>()
        };
        Self {
            pointer: unsafe { NonNull::new_unchecked(pointer) },
        }
    }
    pub(crate) fn into_inner(self) -> T {
        let this = ManuallyDrop::new(self);
        let allocation = this.pointer.as_ptr();
        let value = unsafe { ManuallyDrop::into_inner(ptr::read(&(*allocation).value)) };
        let owner = unsafe { ManuallyDrop::into_inner(ptr::read(&(*allocation).owner)) };
        unsafe {
            System.dealloc(allocation.cast(), Layout::new::<SystemAllocation<T>>());
        }
        drop(owner);
        // Only infrastructure backing was freed. A moved value's ordinary
        // mpsc/Arc/Packet allocations still exist and remain memory-charged.
        value
    }
}
impl<T> Drop for SystemOwned<T> {
    fn drop(&mut self) {
        unsafe {
            ManuallyDrop::drop(&mut (*self.pointer.as_ptr()).value);
        }
        let owner = unsafe { ManuallyDrop::into_inner(ptr::read(&(*self.pointer.as_ptr()).owner)) };
        unsafe {
            System.dealloc(
                self.pointer.as_ptr().cast(),
                Layout::new::<SystemAllocation<T>>(),
            );
        }
        // No T callback or live pointer follows the physical free. Keep the
        // owner through both the destructor and actual System deallocation.
        drop(owner);
    }
}

// Exact existing activation WIT lowering, not a new host import or permission.
// Canonical result<token,error> has tag0/payload8 in its aligned24-byte area.
#[cfg_attr(
    target_arch = "wasm32",
    link(wasm_import_module = "latent:runtime/activation@0.1.0")
)]
unsafe extern "C" {
    #[cfg_attr(target_arch = "wasm32", link_name = "register")]
    fn register(kind: u32, continuation: u32, generation: u64, id: u64, result: *mut u8);
    #[cfg_attr(target_arch = "wasm32", link_name = "park")]
    fn park(generation: u64, id: u64, result: *mut u8);
    #[cfg_attr(target_arch = "wasm32", link_name = "wake")]
    fn wake(generation: u64, id: u64, result: *mut u8);
    #[cfg_attr(target_arch = "wasm32", link_name = "settle")]
    fn settle(generation: u64, id: u64, result: *mut u8);
}
