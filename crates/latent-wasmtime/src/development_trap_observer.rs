//! Test-host-only, explicitly armed numeric observation of one original error.
//!
//! This is not an error sink or authority. No error, module, function name,
//! request or backtrace owner survives capture. Disabled calls do not lock.
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;

use latent_core::{PlatformError, PlatformErrorCode};
use wasmtime::{Module, Trap, WasmBacktrace};

const MAX_FRAMES: usize = 16;

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DevelopmentTrapFrame {
    /// First-seen module ordinal within this one backtrace, not an address.
    pub module: u8,
    pub function: u32,
    pub module_offset: Option<usize>,
    pub function_offset: Option<usize>,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DevelopmentTrapSnapshot {
    pub observed_errors: u32,
    pub ambiguous: bool,
    pub trap_kind: Option<&'static str>,
    pub missing_backtrace: bool,
    pub may_be_truncated: bool,
    pub observed_frames: usize,
    pub engine_frame_cap: Option<usize>,
    pub frames: [Option<DevelopmentTrapFrame>; MAX_FRAMES],
    #[serde(skip_serializing_if = "Option::is_none")]
    pub borrow_admission_refusal: Option<crate::DevelopmentBorrowAdmissionSnapshot>,
}

#[derive(Default)]
struct State {
    armed_once: bool,
    observation: DevelopmentTrapSnapshot,
}

#[derive(Default)]
pub(crate) struct DevelopmentTrapObserver {
    enabled: AtomicBool,
    state: Mutex<State>,
    engine_frame_cap: Option<usize>,
}

/// An explicit test-harness opt-in. Dropping it disables further observation.
pub struct DevelopmentTrapGuard<'a>(&'a DevelopmentTrapObserver);

fn refused() -> PlatformError {
    crate::containment::platform_error(
        PlatformErrorCode::StateConflict,
        "development trap observation unavailable",
        false,
    )
}

impl DevelopmentTrapObserver {
    pub(crate) fn capture_borrow_admission(
        &self,
        snapshot: Option<crate::DevelopmentBorrowAdmissionSnapshot>,
    ) {
        let Some(snapshot) = snapshot else {
            return;
        };
        if !self.enabled.load(Ordering::Acquire) {
            return;
        }
        let Ok(mut state) = self.state.lock() else {
            return;
        };
        if !self.enabled.load(Ordering::Acquire) {
            return;
        }
        if let Some(first) = &mut state.observation.borrow_admission_refusal {
            first.ambiguous = true;
            first.refusals = first.refusals.saturating_add(snapshot.refusals);
        } else {
            state.observation.borrow_admission_refusal = Some(snapshot);
        }
    }

    pub(crate) fn for_engine_configuration(enabled: bool) -> Self {
        Self {
            engine_frame_cap: enabled.then_some(MAX_FRAMES),
            ..Self::default()
        }
    }

    pub(crate) fn arm(&self) -> Result<DevelopmentTrapGuard<'_>, PlatformError> {
        if self.engine_frame_cap != Some(MAX_FRAMES) {
            return Err(refused());
        }
        let mut state = self.state.lock().map_err(|_| refused())?;
        if state.armed_once {
            return Err(refused());
        }
        state.armed_once = true;
        self.enabled.store(true, Ordering::Release);
        Ok(DevelopmentTrapGuard(self))
    }

    pub(crate) fn capture(&self, error: &wasmtime::Error) {
        if !self.enabled.load(Ordering::Acquire) {
            return;
        }
        let Ok(mut state) = self.state.lock() else {
            return; // snapshot reports poison; the original outcome is untouched.
        };
        if !self.enabled.load(Ordering::Acquire) {
            return;
        }
        let observed = &mut state.observation;
        observed.observed_errors = observed.observed_errors.saturating_add(1);
        if observed.observed_errors != 1 {
            observed.ambiguous = true;
            return; // Never replace the first original error.
        }
        observed.engine_frame_cap = self.engine_frame_cap;
        observed.trap_kind = error
            .downcast_ref::<Trap>()
            .map(crate::containment::development_trap_label);
        let Some(backtrace) = error.downcast_ref::<WasmBacktrace>() else {
            observed.missing_backtrace = true;
            return;
        };
        let frames = backtrace.frames();
        observed.observed_frames = frames.len();
        observed.may_be_truncated = frames.len() > MAX_FRAMES
            || self.engine_frame_cap.is_some_and(|cap| frames.len() >= cap);
        let mut modules: [Option<&Module>; MAX_FRAMES] = [None; MAX_FRAMES];
        let mut module_count = 0;
        for (index, frame) in frames.iter().take(MAX_FRAMES).enumerate() {
            let ordinal = modules[..module_count]
                .iter()
                .position(|item| Module::same(item.unwrap(), frame.module()))
                .unwrap_or_else(|| {
                    let ordinal = module_count;
                    modules[ordinal] = Some(frame.module());
                    module_count += 1;
                    ordinal
                });
            observed.frames[index] = Some(DevelopmentTrapFrame {
                module: u8::try_from(ordinal).expect("at most sixteen modules"),
                function: frame.func_index(),
                module_offset: frame.module_offset(),
                function_offset: frame.func_offset(),
            });
        }
    }
}

impl DevelopmentTrapGuard<'_> {
    /// Copies only the fixed numeric record; it cannot retain runtime owners.
    pub fn snapshot(&self) -> Result<DevelopmentTrapSnapshot, PlatformError> {
        self.0
            .state
            .lock()
            .map(|state| state.observation)
            .map_err(|_| refused())
    }
}

impl Drop for DevelopmentTrapGuard<'_> {
    fn drop(&mut self) {
        self.0.enabled.store(false, Ordering::Release);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn disabled_capture_is_empty_and_second_arm_is_refused_even_after_drop() {
        let disabled = DevelopmentTrapObserver::default();
        disabled.capture(&wasmtime::Error::msg("unretained private text"));
        assert!(disabled.arm().is_err());
        let observer = DevelopmentTrapObserver::for_engine_configuration(true);
        observer.capture(&wasmtime::Error::msg("unretained private text"));
        let guard = observer.arm().unwrap();
        assert_eq!(
            guard.snapshot().unwrap(),
            DevelopmentTrapSnapshot::default()
        );
        assert!(observer.arm().is_err());
        drop(guard);
        assert!(observer.arm().is_err());
    }

    #[test]
    fn first_error_is_not_replaced_and_guard_drop_stops_capture() {
        let observer = DevelopmentTrapObserver::for_engine_configuration(true);
        let guard = observer.arm().unwrap();
        observer.capture(&Trap::UnreachableCodeReached.into());
        let first = guard.snapshot().unwrap();
        assert_eq!(first.trap_kind, Some("unreachable-code"));
        assert!(first.missing_backtrace);
        observer.capture(&Trap::IntegerDivisionByZero.into());
        let second = guard.snapshot().unwrap();
        assert_eq!(second.observed_errors, 2);
        assert!(second.ambiguous);
        assert_eq!(second.trap_kind, first.trap_kind);
        drop(guard);
        observer.capture(&Trap::StackOverflow.into());
        assert_eq!(observer.state.lock().unwrap().observation, second);
    }

    #[test]
    fn actual_backtrace_is_bounded_numeric_and_does_not_retain_runtime_owners() {
        use wasm_encoder::{
            CodeSection, ExportKind, ExportSection, Function, FunctionSection, Instruction,
            Module as Encoder, TypeSection,
        };
        let mut wasm = Encoder::new();
        let mut types = TypeSection::new();
        types.ty().function([], []);
        wasm.section(&types);
        let mut functions = FunctionSection::new();
        for _ in 0..20 {
            functions.function(0);
        }
        wasm.section(&functions);
        let mut exports = ExportSection::new();
        exports.export("run", ExportKind::Func, 19);
        wasm.section(&exports);
        let mut code = CodeSection::new();
        for index in 0..20 {
            let mut body = Function::new([]);
            if index == 0 {
                body.instruction(&Instruction::Unreachable);
            } else {
                body.instruction(&Instruction::Call(index - 1));
            }
            body.instruction(&Instruction::End);
            code.function(&body);
        }
        wasm.section(&code);
        let bytes = wasm.finish();
        let mut selected = crate::WasmtimeConfig::default();
        let original_settings = serde_json::to_value(
            crate::config::CompilerEngineSettings::from_config(&selected),
        )
        .unwrap();
        assert!(original_settings
            .get("developmentNumericTrapObservation")
            .is_none());
        let original_profile = selected.configuration_digest(crate::config::DispatchMode::Generic);
        {
            let engine = selected.runtime_engine().unwrap();
            let module = Module::new(&engine, &bytes).unwrap();
            let mut store = wasmtime::Store::new(&engine, ());
            store.set_fuel(1_000_000).unwrap();
            store.set_epoch_deadline(1_000);
            let instance = wasmtime::Instance::new(&mut store, &module, &[]).unwrap();
            let function = instance
                .get_typed_func::<(), ()>(&mut store, "run")
                .unwrap();
            let error = function.call(&mut store, ()).unwrap_err();
            assert!(error.downcast_ref::<WasmBacktrace>().is_none());
        }
        selected.development_numeric_trap_observation = true;
        let selected_settings = serde_json::to_value(
            crate::config::CompilerEngineSettings::from_config(&selected),
        )
        .unwrap();
        assert_eq!(selected_settings["developmentNumericTrapObservation"], true);
        assert_ne!(
            selected.configuration_digest(crate::config::DispatchMode::Generic),
            original_profile
        );
        let observer = DevelopmentTrapObserver::for_engine_configuration(true);
        let guard = observer.arm().unwrap();
        {
            let engine = selected.runtime_engine().unwrap();
            let module = Module::new(&engine, &bytes).unwrap();
            let mut store = wasmtime::Store::new(&engine, ());
            store.set_fuel(1_000_000).unwrap();
            store.set_epoch_deadline(1_000);
            let instance = wasmtime::Instance::new(&mut store, &module, &[]).unwrap();
            let function = instance
                .get_typed_func::<(), ()>(&mut store, "run")
                .unwrap();
            let error = function.call(&mut store, ()).unwrap_err();
            observer.capture(&error);
        } // Original error, Store, Module and Engine are all destroyed first.
        let value = guard.snapshot().unwrap();
        assert_eq!(value.observed_errors, 1);
        assert_eq!(value.trap_kind, Some("unreachable-code"));
        assert!(!value.missing_backtrace && !value.ambiguous && value.may_be_truncated);
        assert_eq!(value.observed_frames, 16);
        assert_eq!(value.engine_frame_cap, Some(16));
        assert_eq!(value.frames.iter().flatten().count(), MAX_FRAMES);
        for frame in value.frames.iter().flatten() {
            assert_eq!(frame.module, 0);
            assert!(frame.function < 20);
            assert!(frame.module_offset.is_some() && frame.function_offset.is_some());
        }
        assert!(serde_json::to_vec(&value).unwrap().len() <= 8192);
    }
}

// Separate scalar diagnostic. The original frame observer above is unchanged.
// This record cannot authorize retirement or replace a terminal result.
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub enum DevelopmentJoinCause {
    Quiescence,
    OriginalFault,
    Unexpected,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DevelopmentJoinCauseSnapshot {
    pub claims: u8,
    pub invalid: bool,
    pub cause: Option<DevelopmentJoinCause>,
}

/// First closed refusal; it is diagnostic and cannot authorize a cause.
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub enum DevelopmentJoinRejectReason {
    ClaimRepeated,
    ComponentMismatch,
    ContractMismatch,
    ExportMismatch,
    CallFailed,
    LiftFailed,
    WrongShape,
    UnknownWord,
    DuplicateCapture,
    SessionUnavailable,
    SessionClosed,
    NativeDuplicateReturn,
    NativeInvalidReturn,
}

#[derive(Clone, Copy, Default)]
struct JoinCauseSlot {
    armed_once: bool,
    enabled: bool,
    component: [u8; 32],
    observation: DevelopmentJoinCauseSnapshot,
    rejection: Option<DevelopmentJoinRejectReason>,
    task_return_enabled: bool,
    task_return: DevelopmentJoinCauseSnapshot,
}

#[derive(Default)]
pub(crate) struct DevelopmentJoinCauseObserver {
    enabled: AtomicBool,
    slots: Mutex<[JoinCauseSlot; 3]>,
}

/// Borrowed test-host arming; no component, request, value or runtime owner retained.
pub struct DevelopmentJoinCauseGuard<'a> {
    observer: &'a DevelopmentJoinCauseObserver,
    slot: usize,
}

/// Separate canonical TaskReturn-stage witness; never an outer-call success.
pub struct DevelopmentTaskReturnGuard<'a> {
    original: DevelopmentJoinCauseGuard<'a>,
}

fn join_cause_refused() -> PlatformError {
    crate::containment::platform_error(
        PlatformErrorCode::StateConflict,
        "development Join cause observation unavailable",
        false,
    )
}

fn join_cause_slot(activation: &str) -> Option<usize> {
    match activation {
        "dotnet-ac7-diag-quiescence" => Some(0),
        "dotnet-ac7-diag-original-fault" => Some(1),
        "dotnet-ac7-diag-unexpected" => Some(2),
        _ => None,
    }
}

fn join_cause_digest(value: &str) -> Option<[u8; 32]> {
    let raw = value.strip_prefix("sha256:")?.as_bytes();
    if raw.len() != 64 {
        return None;
    }
    let mut output = [0; 32];
    for (index, pair) in raw.chunks_exact(2).enumerate() {
        let digit = |v| match v {
            b'0'..=b'9' => Some(v - b'0'),
            b'a'..=b'f' => Some(v - b'a' + 10),
            _ => None,
        };
        output[index] = (digit(pair[0])? << 4) | digit(pair[1])?;
    }
    Some(output)
}

impl DevelopmentJoinCauseObserver {
    pub(crate) fn arm(
        &self,
        activation: &str,
        component: &str,
        contract: &str,
        export: &str,
    ) -> Result<DevelopmentJoinCauseGuard<'_>, PlatformError> {
        let slot = join_cause_slot(activation).ok_or_else(join_cause_refused)?;
        let component = join_cause_digest(component).ok_or_else(join_cause_refused)?;
        if contract != "examples:greeting/api@1.0.0" || export != "probe" {
            return Err(join_cause_refused());
        }
        let mut slots = self.slots.lock().map_err(|_| join_cause_refused())?;
        if slots[slot].armed_once {
            return Err(join_cause_refused());
        }
        slots[slot].armed_once = true;
        slots[slot].enabled = true;
        slots[slot].component = component;
        self.enabled.store(true, Ordering::Release);
        Ok(DevelopmentJoinCauseGuard {
            observer: self,
            slot,
        })
    }

    /// Called only after ordinary admission and before the request moves into Store.
    pub(crate) fn claim(
        &self,
        activation: &str,
        component: Option<&str>,
        contract: &str,
        export: &str,
    ) -> Option<usize> {
        if !self.enabled.load(Ordering::Acquire) {
            return None;
        }
        let slot = join_cause_slot(activation)?;
        let Ok(mut slots) = self.slots.lock() else {
            return None;
        };
        let selected = &mut slots[slot];
        if !selected.enabled {
            return None;
        }
        selected.observation.claims = selected.observation.claims.saturating_add(1);
        if selected.observation.claims != 1
            || component.and_then(join_cause_digest) != Some(selected.component)
            || contract != "examples:greeting/api@1.0.0"
            || export != "probe"
        {
            selected
                .rejection
                .get_or_insert(if selected.observation.claims != 1 {
                    DevelopmentJoinRejectReason::ClaimRepeated
                } else if component.and_then(join_cause_digest) != Some(selected.component) {
                    DevelopmentJoinRejectReason::ComponentMismatch
                } else if contract != "examples:greeting/api@1.0.0" {
                    DevelopmentJoinRejectReason::ContractMismatch
                } else {
                    DevelopmentJoinRejectReason::ExportMismatch
                });
            selected.observation.invalid = true;
            if selected.task_return_enabled {
                selected.task_return.invalid = true;
            }
            return None;
        }
        Some(slot)
    }

    /// Borrow exactly one already-lifted U32 before the UNCHANGED finalizer.
    pub(crate) fn capture(
        &self,
        claim: Option<usize>,
        call_ok: bool,
        lift_ok: bool,
        types: &[wasmtime::component::Type],
        values: &[wasmtime::component::Val],
    ) {
        let Some(slot) = claim else {
            return;
        };
        let Ok(mut slots) = self.slots.lock() else {
            return;
        };
        let selected = &mut slots[slot];
        if !selected.enabled {
            return;
        }
        let cause = match (call_ok, lift_ok, types, values) {
            (
                true,
                true,
                [wasmtime::component::Type::U32],
                [wasmtime::component::Val::U32(word)],
            ) => match *word {
                0x4A43_0001 => Some(DevelopmentJoinCause::Quiescence),
                0x4A43_0002 => Some(DevelopmentJoinCause::OriginalFault),
                0x4A43_0003 => Some(DevelopmentJoinCause::Unexpected),
                _ => None,
            },
            _ => None,
        };
        if selected.observation.invalid || selected.observation.cause.is_some() || cause.is_none() {
            selected
                .rejection
                .get_or_insert(if selected.observation.cause.is_some() {
                    DevelopmentJoinRejectReason::DuplicateCapture
                } else if !call_ok {
                    DevelopmentJoinRejectReason::CallFailed
                } else if !lift_ok {
                    DevelopmentJoinRejectReason::LiftFailed
                } else if matches!(
                    (types, values),
                    (
                        [wasmtime::component::Type::U32],
                        [wasmtime::component::Val::U32(_)]
                    )
                ) {
                    DevelopmentJoinRejectReason::UnknownWord
                } else {
                    DevelopmentJoinRejectReason::WrongShape
                });
            selected.observation.invalid = true;
            return;
        }
        selected.observation.cause = cause;
    }
}

impl DevelopmentJoinCauseGuard<'_> {
    pub fn rejection(&self) -> Result<Option<DevelopmentJoinRejectReason>, PlatformError> {
        self.observer
            .slots
            .lock()
            .map(|slots| slots[self.slot].rejection)
            .map_err(|_| join_cause_refused())
    }
    pub fn snapshot(&self) -> Result<DevelopmentJoinCauseSnapshot, PlatformError> {
        self.observer
            .slots
            .lock()
            .map(|slots| slots[self.slot].observation)
            .map_err(|_| join_cause_refused())
    }
}

impl DevelopmentJoinCauseObserver {
    pub(crate) fn arm_task_return(
        &self,
        activation: &str,
        component: &str,
        contract: &str,
        export: &str,
    ) -> Result<DevelopmentTaskReturnGuard<'_>, PlatformError> {
        let original = self.arm(activation, component, contract, export)?;
        self.slots.lock().map_err(|_| join_cause_refused())?[original.slot].task_return_enabled =
            true;
        Ok(DevelopmentTaskReturnGuard { original })
    }

    pub(crate) fn task_return_enabled(&self, claim: Option<usize>) -> bool {
        let Some(slot) = claim else { return false };
        self.slots.lock().is_ok_and(|slots| {
            let Some(selected) = slots.get(slot) else {
                return false;
            };
            selected.enabled
                && selected.task_return_enabled
                && selected.observation.claims == 1
                && !selected.observation.invalid
        })
    }

    pub(crate) fn reject_task_return(&self, slot: usize, reason: DevelopmentJoinRejectReason) {
        let Ok(mut slots) = self.slots.lock() else {
            return;
        };
        let Some(selected) = slots.get_mut(slot) else {
            return;
        };
        if selected.enabled && selected.task_return_enabled {
            selected.rejection.get_or_insert(reason);
            selected.task_return.invalid = true;
        }
    }

    pub(crate) fn native_task_return_failure(&self, claim: Option<usize>, duplicate: bool) {
        if let Some(slot) = claim {
            self.reject_task_return(
                slot,
                if duplicate {
                    DevelopmentJoinRejectReason::NativeDuplicateReturn
                } else {
                    DevelopmentJoinRejectReason::NativeInvalidReturn
                },
            );
        }
    }

    pub(crate) fn capture_task_return(
        &self,
        slot: usize,
        session_live: bool,
        event: wasmtime::component::DevelopmentTaskReturnEvent,
    ) {
        use wasmtime::component::DevelopmentTaskReturnEvent as Event;
        let Ok(mut slots) = self.slots.lock() else {
            return;
        };
        let Some(selected) = slots.get_mut(slot) else {
            return;
        };
        if !selected.enabled || !selected.task_return_enabled {
            return;
        }
        selected.task_return.claims = selected.task_return.claims.saturating_add(1);
        let cause = match event {
            Event::Quiescence => Some(DevelopmentJoinCause::Quiescence),
            Event::OriginalFault => Some(DevelopmentJoinCause::OriginalFault),
            Event::Unexpected => Some(DevelopmentJoinCause::Unexpected),
            Event::WrongShape | Event::UnknownWord => None,
        };
        let reject = if !session_live {
            Some(DevelopmentJoinRejectReason::SessionClosed)
        } else if selected.observation.claims != 1 || selected.observation.invalid {
            Some(DevelopmentJoinRejectReason::ClaimRepeated)
        } else if selected.task_return.claims != 1 || selected.task_return.cause.is_some() {
            Some(DevelopmentJoinRejectReason::DuplicateCapture)
        } else if cause.is_none() {
            Some(if event == Event::WrongShape {
                DevelopmentJoinRejectReason::WrongShape
            } else {
                DevelopmentJoinRejectReason::UnknownWord
            })
        } else {
            None
        };
        if let Some(reason) = reject {
            selected.rejection.get_or_insert(reason);
            selected.task_return.invalid = true;
        } else if !selected.task_return.invalid {
            selected.task_return.cause = cause;
        }
    }
}

impl DevelopmentTaskReturnGuard<'_> {
    pub fn snapshot(&self) -> Result<DevelopmentJoinCauseSnapshot, PlatformError> {
        self.original
            .observer
            .slots
            .lock()
            .map(|slots| slots[self.original.slot].task_return)
            .map_err(|_| join_cause_refused())
    }
    pub fn post_call_snapshot(&self) -> Result<DevelopmentJoinCauseSnapshot, PlatformError> {
        self.original.snapshot()
    }
    pub fn rejection(&self) -> Result<Option<DevelopmentJoinRejectReason>, PlatformError> {
        self.original.rejection()
    }
}
impl Drop for DevelopmentJoinCauseGuard<'_> {
    fn drop(&mut self) {
        if let Ok(mut slots) = self.observer.slots.lock() {
            slots[self.slot].enabled = false;
            self.observer
                .enabled
                .store(slots.iter().any(|slot| slot.enabled), Ordering::Release);
        }
    }
}

#[cfg(test)]
mod join_cause_tests {
    use super::*;
    use wasmtime::component::{Type, Val};
    const DIGEST: &str = "sha256:0000000000000000000000000000000000000000000000000000000000000001";
    const ID: &str = "dotnet-ac7-diag-original-fault";
    const CONTRACT: &str = "examples:greeting/api@1.0.0";

    #[test]
    fn scalar_observer_is_closed_single_claim_and_never_replaces_first() {
        let observer = DevelopmentJoinCauseObserver::default();
        assert!(observer
            .claim(ID, Some(DIGEST), CONTRACT, "probe")
            .is_none());
        assert!(observer.arm("other", DIGEST, CONTRACT, "probe").is_err());
        assert!(observer.arm(ID, DIGEST, CONTRACT, "other").is_err());
        let guard = observer.arm(ID, DIGEST, CONTRACT, "probe").unwrap();
        let claim = observer.claim(ID, Some(DIGEST), CONTRACT, "probe");
        observer.capture(claim, true, true, &[Type::U32], &[Val::U32(0x4A43_0002)]);
        assert_eq!(
            guard.snapshot().unwrap().cause,
            Some(DevelopmentJoinCause::OriginalFault)
        );
        assert!(observer
            .claim(ID, Some(DIGEST), CONTRACT, "probe")
            .is_none());
        let result = guard.snapshot().unwrap();
        assert_eq!(result.claims, 2);
        assert!(result.invalid);
        assert_eq!(result.cause, Some(DevelopmentJoinCause::OriginalFault));
        drop(guard);
        assert!(observer.arm(ID, DIGEST, CONTRACT, "probe").is_err());

        let early = DevelopmentJoinCauseObserver::default();
        let guard = early
            .arm_task_return(ID, DIGEST, CONTRACT, "probe")
            .unwrap();
        let claim = early.claim(ID, Some(DIGEST), CONTRACT, "probe");
        assert!(early.task_return_enabled(claim));
        early.capture_task_return(
            claim.unwrap(),
            true,
            wasmtime::component::DevelopmentTaskReturnEvent::OriginalFault,
        );
        // A successful earlier typed lift never makes the failed outer call valid.
        early.capture(claim, false, true, &[Type::U32], &[]);
        assert!(guard.post_call_snapshot().unwrap().invalid);
        assert_eq!(
            guard.rejection().unwrap(),
            Some(DevelopmentJoinRejectReason::CallFailed)
        );
        assert_eq!(
            guard.snapshot().unwrap().cause,
            Some(DevelopmentJoinCause::OriginalFault)
        );
        assert!(!guard.snapshot().unwrap().invalid);
        early.capture_task_return(
            claim.unwrap(),
            true,
            wasmtime::component::DevelopmentTaskReturnEvent::Unexpected,
        );
        assert!(guard.snapshot().unwrap().invalid);
        assert_eq!(
            guard.snapshot().unwrap().cause,
            Some(DevelopmentJoinCause::OriginalFault)
        );
        assert_eq!(
            guard.rejection().unwrap(),
            Some(DevelopmentJoinRejectReason::CallFailed)
        );
        drop(guard);
        assert!(!early.task_return_enabled(claim));

        let repeated = DevelopmentJoinCauseObserver::default();
        let guard = repeated
            .arm_task_return(ID, DIGEST, CONTRACT, "probe")
            .unwrap();
        let claim = repeated.claim(ID, Some(DIGEST), CONTRACT, "probe");
        repeated.capture_task_return(
            claim.unwrap(),
            true,
            wasmtime::component::DevelopmentTaskReturnEvent::OriginalFault,
        );
        assert!(!guard.snapshot().unwrap().invalid);
        assert!(repeated
            .claim(ID, Some(DIGEST), CONTRACT, "probe")
            .is_none());
        assert!(guard.snapshot().unwrap().invalid);
        assert_eq!(
            guard.snapshot().unwrap().cause,
            Some(DevelopmentJoinCause::OriginalFault)
        );
        assert_eq!(
            guard.rejection().unwrap(),
            Some(DevelopmentJoinRejectReason::ClaimRepeated)
        );
    }

    #[test]
    fn failed_call_lift_wrong_digest_shape_and_nonword_are_never_causes() {
        for variant in 0..6 {
            let observer = DevelopmentJoinCauseObserver::default();
            let guard = observer.arm(ID, DIGEST, CONTRACT, "probe").unwrap();
            let digest = if variant == 2 { None } else { Some(DIGEST) };
            let claim = observer.claim(ID, digest, CONTRACT, "probe");
            let (types, values) = if variant == 3 {
                (vec![Type::S32], vec![Val::S32(42)])
            } else if variant == 4 {
                (vec![Type::U32, Type::U32], vec![Val::U32(42), Val::U32(42)])
            } else {
                (vec![Type::U32], vec![Val::U32(42)])
            };
            observer.capture(claim, variant != 0, variant != 1, &types, &values);
            let result = guard.snapshot().unwrap();
            assert!(result.invalid);
            assert!(result.cause.is_none());
        }
        for event in [
            wasmtime::component::DevelopmentTaskReturnEvent::WrongShape,
            wasmtime::component::DevelopmentTaskReturnEvent::UnknownWord,
        ] {
            let observer = DevelopmentJoinCauseObserver::default();
            let guard = observer
                .arm_task_return(ID, DIGEST, CONTRACT, "probe")
                .unwrap();
            let claim = observer.claim(ID, Some(DIGEST), CONTRACT, "probe");
            observer.capture_task_return(claim.unwrap(), true, event);
            assert!(guard.snapshot().unwrap().invalid);
            assert!(guard.snapshot().unwrap().cause.is_none());
            let first_reason = guard.rejection().unwrap();
            observer.capture_task_return(
                claim.unwrap(),
                true,
                wasmtime::component::DevelopmentTaskReturnEvent::OriginalFault,
            );
            assert_eq!(guard.snapshot().unwrap().claims, 2);
            assert!(guard.snapshot().unwrap().invalid);
            assert!(guard.snapshot().unwrap().cause.is_none());
            assert_eq!(guard.rejection().unwrap(), first_reason);
        }
        {
            let observer = DevelopmentJoinCauseObserver::default();
            let guard = observer
                .arm_task_return(ID, DIGEST, CONTRACT, "probe")
                .unwrap();
            let claim = observer.claim(ID, Some(DIGEST), CONTRACT, "probe");
            observer.capture_task_return(
                claim.unwrap(),
                false,
                wasmtime::component::DevelopmentTaskReturnEvent::OriginalFault,
            );
            assert_eq!(guard.snapshot().unwrap().claims, 1);
            assert!(guard.snapshot().unwrap().invalid);
            assert!(guard.snapshot().unwrap().cause.is_none());
            assert_eq!(
                guard.rejection().unwrap(),
                Some(DevelopmentJoinRejectReason::SessionClosed)
            );
        }
        for unavailable in [
            DevelopmentJoinRejectReason::SessionUnavailable,
            DevelopmentJoinRejectReason::SessionClosed,
        ] {
            let observer = DevelopmentJoinCauseObserver::default();
            let guard = observer
                .arm_task_return(ID, DIGEST, CONTRACT, "probe")
                .unwrap();
            let claim = observer.claim(ID, Some(DIGEST), CONTRACT, "probe");
            observer.reject_task_return(claim.unwrap(), unavailable);
            observer.capture_task_return(
                claim.unwrap(),
                true,
                wasmtime::component::DevelopmentTaskReturnEvent::OriginalFault,
            );
            assert!(guard.snapshot().unwrap().invalid);
            assert!(guard.snapshot().unwrap().cause.is_none());
            assert_eq!(guard.rejection().unwrap(), Some(unavailable));
        }
        let observer = DevelopmentJoinCauseObserver::default();
        let guard = observer
            .arm_task_return(ID, DIGEST, CONTRACT, "probe")
            .unwrap();
        let claim = observer.claim(ID, None, CONTRACT, "probe");
        assert!(claim.is_none());
        assert!(!observer.task_return_enabled(claim));
        assert!(guard.post_call_snapshot().unwrap().invalid);
        assert_eq!(
            guard.rejection().unwrap(),
            Some(DevelopmentJoinRejectReason::ComponentMismatch)
        );
    }

    #[test]
    fn three_words_have_distinct_causes_without_any_frame_or_result_owner() {
        for (word, cause) in [
            (0x4A43_0001, DevelopmentJoinCause::Quiescence),
            (0x4A43_0002, DevelopmentJoinCause::OriginalFault),
            (0x4A43_0003, DevelopmentJoinCause::Unexpected),
        ] {
            let observer = DevelopmentJoinCauseObserver::default();
            let guard = observer.arm(ID, DIGEST, CONTRACT, "probe").unwrap();
            let claim = observer.claim(ID, Some(DIGEST), CONTRACT, "probe");
            observer.capture(claim, true, true, &[Type::U32], &[Val::U32(word)]);
            assert_eq!(
                guard.snapshot().unwrap(),
                DevelopmentJoinCauseSnapshot {
                    claims: 1,
                    invalid: false,
                    cause: Some(cause),
                }
            );
        }
        for (event, cause) in [
            (
                wasmtime::component::DevelopmentTaskReturnEvent::Quiescence,
                DevelopmentJoinCause::Quiescence,
            ),
            (
                wasmtime::component::DevelopmentTaskReturnEvent::OriginalFault,
                DevelopmentJoinCause::OriginalFault,
            ),
            (
                wasmtime::component::DevelopmentTaskReturnEvent::Unexpected,
                DevelopmentJoinCause::Unexpected,
            ),
        ] {
            let observer = DevelopmentJoinCauseObserver::default();
            let guard = observer
                .arm_task_return(ID, DIGEST, CONTRACT, "probe")
                .unwrap();
            let claim = observer.claim(ID, Some(DIGEST), CONTRACT, "probe");
            observer.capture_task_return(claim.unwrap(), true, event);
            assert_eq!(
                guard.snapshot().unwrap(),
                DevelopmentJoinCauseSnapshot {
                    claims: 1,
                    invalid: false,
                    cause: Some(cause),
                }
            );
            observer.native_task_return_failure(claim, true);
            assert!(guard.snapshot().unwrap().invalid);
            assert_eq!(guard.snapshot().unwrap().cause, Some(cause));
            assert_eq!(
                guard.rejection().unwrap(),
                Some(DevelopmentJoinRejectReason::NativeDuplicateReturn)
            );
        }
    }
}
