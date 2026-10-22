//! Copied owner implementation with explicit canonical/allocator test ports.
//! This proves source ordering and layouts, not a selected sysroot or host run.
use std::cell::RefCell;
use std::collections::BTreeMap;
pub use std::{mem, ptr};
#[derive(Default)]
struct Ports {
    next: u64,
    live: BTreeMap<(u64, u64), u32>,
    allocations: BTreeMap<usize, (usize, usize)>,
    events: Vec<&'static str>,
    registration_error: Option<u8>,
    operation_error: Option<u8>,
    malformed: u8,
    allocation_fail: bool,
}
std::thread_local! { static PORTS: RefCell<Ports> = RefCell::new(Ports::default()); }
fn event(value: &'static str) {
    PORTS.with(|p| p.borrow_mut().events.push(value));
}
fn live() -> usize {
    PORTS.with(|p| p.borrow().live.len())
}
fn events() -> Vec<&'static str> {
    PORTS.with(|p| p.borrow().events.clone())
}
fn reset() {
    PORTS.with(|p| {
        assert!(p.borrow().live.is_empty());
        assert!(p.borrow().allocations.is_empty());
        *p.borrow_mut() = Ports::default();
    });
}

pub mod alloc {
    pub use std::alloc::{GlobalAlloc, Layout};
    pub struct System;
    unsafe impl GlobalAlloc for System {
        unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
            assert_eq!(super::live(), 1, "real admission before allocation");
            if super::PORTS.with(|p| p.borrow().allocation_fail) {
                super::event("allocation-refused");
                return std::ptr::null_mut();
            }
            let pointer = unsafe { std::alloc::System.alloc(layout) };
            assert!(!pointer.is_null());
            super::PORTS.with(|p| {
                assert!(
                    p.borrow_mut()
                        .allocations
                        .insert(pointer as usize, (layout.size(), layout.align()))
                        .is_none()
                )
            });
            super::event("allocated");
            pointer
        }
        unsafe fn dealloc(&self, pointer: *mut u8, layout: Layout) {
            assert_eq!(super::live(), 1, "owner cannot settle before actual free");
            super::PORTS.with(|p| {
                assert_eq!(
                    p.borrow_mut().allocations.remove(&(pointer as usize)),
                    Some((layout.size(), layout.align())),
                    "free must match actual full backing"
                )
            });
            unsafe {
                std::alloc::System.dealloc(pointer, layout);
            }
            super::event("freed");
        }
    }
}
#[path = "../runtime_owner.rs"]
mod owner;
use owner::{AllocationError, Error, Kind, Owner, SystemOwned, Token};
const GENERATION: u64 = 0x1122_3344_5566_7788;

#[unsafe(no_mangle)]
unsafe extern "C" fn register(kind: u32, present: u32, generation: u64, id: u64, result: *mut u8) {
    assert_eq!(result as usize % 8, 0);
    assert!(kind <= 7 && present <= 1);
    PORTS.with(|p| {
        let mut p = p.borrow_mut();
        p.events.push("registered");
        if let Some(code) = p.registration_error {
            unsafe {
                result.write(1);
                result.add(8).write(code);
            }
            return;
        }
        if present == 0 {
            assert_eq!((generation, id), (0, 0));
        } else {
            assert!(p.live.contains_key(&(generation, id)));
        }
        if p.malformed == 1 {
            unsafe {
                result.write(2);
            }
            return;
        }
        p.next += 1;
        let id = 0x8877_6655_4433_2200 + p.next;
        let token = if p.malformed == 2 {
            (0, id)
        } else {
            (GENERATION, id)
        };
        unsafe {
            result.write(0);
            std::ptr::copy_nonoverlapping(token.0.to_le_bytes().as_ptr(), result.add(8), 8);
            std::ptr::copy_nonoverlapping(token.1.to_le_bytes().as_ptr(), result.add(16), 8);
        }
        if token.0 != 0 {
            assert!(p.live.insert(token, kind).is_none());
        }
    });
}
fn operation(name: &'static str, generation: u64, id: u64, result: *mut u8) {
    PORTS.with(|p| {
        let mut p = p.borrow_mut();
        assert!(p.live.contains_key(&(generation, id)));
        p.events.push(name);
        let code = p.operation_error;
        unsafe {
            result.write(code.is_some() as u8);
            result.add(1).write(code.unwrap_or(0));
        }
    });
}
#[unsafe(no_mangle)]
unsafe extern "C" fn park(generation: u64, id: u64, result: *mut u8) {
    operation("parked", generation, id, result);
}
#[unsafe(no_mangle)]
unsafe extern "C" fn wake(generation: u64, id: u64, result: *mut u8) {
    operation("woken", generation, id, result);
}
#[unsafe(no_mangle)]
unsafe extern "C" fn settle(generation: u64, id: u64, result: *mut u8) {
    PORTS.with(|p| {
        let mut p = p.borrow_mut();
        assert!(p.live.remove(&(generation, id)).is_some());
        p.events.push("settled");
    });
    unsafe {
        result.write(0);
    }
}
struct Value(u64);
impl Drop for Value {
    fn drop(&mut self) {
        assert_eq!(live(), 1);
        event("value-dropped");
    }
}

#[test]
fn real_system_backing_and_value_destructor_precede_exactly_once_settlement() {
    reset();
    let value = SystemOwned::try_new(Value(42), None).unwrap();
    assert_eq!(unsafe { value.pointer().as_ref().0 }, 42);
    assert_eq!(value.token().generation, GENERATION);
    drop(value);
    assert_eq!(
        events(),
        [
            "registered",
            "allocated",
            "value-dropped",
            "freed",
            "settled"
        ]
    );
    assert_eq!(live(), 0);
}
#[test]
fn original_error_variants_refuse_before_any_system_allocation() {
    for (code, error) in [
        Error::Unavailable,
        Error::PermissionDenied,
        Error::ResourceExhausted,
        Error::Cancelled,
        Error::Deadline,
        Error::InvalidState,
        Error::InvalidToken,
    ]
    .into_iter()
    .enumerate()
    {
        reset();
        PORTS.with(|p| p.borrow_mut().registration_error = Some(code as u8));
        assert!(
            matches!(SystemOwned::try_new(42u64,None),Err(AllocationError::Admission(actual))if actual==error)
        );
        assert_eq!(events(), ["registered"]);
        assert_eq!(live(), 0);
    }
}
#[test]
fn failed_actual_system_allocation_rolls_back_admission_without_publishing_backing() {
    reset();
    PORTS.with(|p| p.borrow_mut().allocation_fail = true);
    assert!(matches!(
        SystemOwned::try_new(42u64, None),
        Err(AllocationError::Allocation)
    ));
    assert_eq!(events(), ["registered", "allocation-refused", "settled"]);
    assert_eq!(live(), 0);
}
#[test]
fn moving_value_frees_only_infrastructure_backing_then_transfers_ordinary_value() {
    reset();
    let value = SystemOwned::try_new(42u64, None).unwrap().into_inner();
    assert_eq!(value, 42);
    assert_eq!(events(), ["registered", "allocated", "freed", "settled"]);
    assert_eq!(live(), 0);
}
#[test]
fn intrusive_transfer_retains_real_backing_and_owner_until_unique_recovery_and_drop() {
    reset();
    let original = SystemOwned::try_new(Value(91), None).unwrap();
    let token = original.token();
    let pointer = original.into_raw();
    assert_eq!(events(), ["registered", "allocated"]);
    assert_eq!(live(), 1);
    assert_eq!(unsafe { pointer.as_ref().0 }, 91);
    let recovered = unsafe { SystemOwned::from_raw(pointer) };
    assert_eq!(recovered.token(), token);
    drop(recovered);
    assert_eq!(
        events(),
        [
            "registered",
            "allocated",
            "value-dropped",
            "freed",
            "settled"
        ]
    );
    assert_eq!(live(), 0);
}
#[test]
fn intrusive_header_preserves_large_alignment_and_frees_the_original_complete_allocation() {
    #[repr(align(64))]
    struct Aligned([u8; 65]);
    reset();
    let pointer = SystemOwned::try_new(Aligned([7; 65]), None)
        .unwrap()
        .into_raw();
    assert_eq!(pointer.as_ptr() as usize % 64, 0);
    assert_eq!(unsafe { pointer.as_ref().0 }, [7; 65]);
    let value = unsafe { SystemOwned::from_raw(pointer) }.into_inner();
    assert_eq!(value.0, [7; 65]);
    assert_eq!(events(), ["registered", "allocated", "freed", "settled"]);
    assert_eq!(live(), 0);
}
#[test]
fn full_u64_token_and_parent_are_preserved_with_no_zero_parent_alias() {
    reset();
    let parent = Owner::admit(Kind::Task, None).unwrap();
    let child = Owner::admit(Kind::QueuedWork, Some(parent.token())).unwrap();
    assert!(child.token().id > u32::MAX as u64);
    assert_eq!(live(), 2);
    drop(child);
    drop(parent);
    assert_eq!(live(), 0);
    reset();
    assert!(matches!(
        Owner::admit(
            Kind::Wait,
            Some(Token {
                generation: 0,
                id: 7
            })
        ),
        Err(Error::InvalidToken)
    ));
    assert!(events().is_empty());
}
#[test]
fn park_and_wake_preserve_exact_errors_without_settling_live_work() {
    reset();
    let owner = Owner::admit(Kind::Task, None).unwrap();
    owner.park().unwrap();
    owner.wake().unwrap();
    for (code, error) in [
        Error::Unavailable,
        Error::PermissionDenied,
        Error::ResourceExhausted,
        Error::Cancelled,
        Error::Deadline,
        Error::InvalidState,
        Error::InvalidToken,
    ]
    .into_iter()
    .enumerate()
    {
        PORTS.with(|p| p.borrow_mut().operation_error = Some(code as u8));
        assert_eq!(owner.park(), Err(error));
        assert_eq!(owner.wake(), Err(error));
        assert_eq!(live(), 1);
    }
    drop(owner);
    assert_eq!(live(), 0);
    assert_eq!(events().iter().filter(|row| **row == "settled").count(), 1);
}
#[test]
fn malformed_register_tags_tokens_and_error_discriminants_never_become_success() {
    for malformed in [1, 2] {
        reset();
        PORTS.with(|p| p.borrow_mut().malformed = malformed);
        assert!(std::panic::catch_unwind(|| Owner::admit(Kind::Native, None)).is_err());
        assert_eq!(live(), 0);
    }
    reset();
    PORTS.with(|p| p.borrow_mut().registration_error = Some(7));
    assert!(std::panic::catch_unwind(|| Owner::admit(Kind::Native, None)).is_err());
    assert_eq!(live(), 0);
}
