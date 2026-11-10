//! Bounded event ordering for the selected fired-one-shot diagnostic.
//! Event-state controls alone do not establish signed guest execution.
use latent_core::activation_runtime::RuntimeToken as Token;
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Mode {
    Stop,
    Reset,
}
#[derive(Clone, Copy, Debug)]
#[expect(
    clippy::struct_excessive_bools,
    reason = "distinct observed edges must be independently retained until final evidence"
)]
pub struct Witness {
    mode: Mode,
    root: Token,
    target: Option<Token>,
    marker: Option<Token>,
    replacement: Option<Token>,
    next_live: bool,
    next_pending: bool,
    held: bool,
    target_stopped: bool,
    probe: bool,
    dropped: bool,
    replacement_stopped: bool,
    marker_stopped: bool,
    invalid: bool,
}
impl Witness {
    pub fn new(mode: Mode, root: Token) -> Self {
        Self {
            mode,
            root,
            target: None,
            marker: None,
            replacement: None,
            next_live: false,
            next_pending: false,
            held: false,
            target_stopped: false,
            probe: false,
            dropped: false,
            replacement_stopped: false,
            marker_stopped: false,
            invalid: false,
        }
    }
    pub fn timer_start(&mut self, token: Token, parent: Token, periodic: bool) {
        if self.invalid {
            return;
        }
        if parent != self.root || periodic {
            self.invalid = true;
            return;
        }
        if self.target.is_none() {
            self.target = Some(token);
            return;
        }
        if self.marker.is_none() {
            if self.held
                && self.next_pending
                && self.next_live
                && self.target_stopped
                && Some(token) != self.target
            {
                self.marker = Some(token);
            } else {
                self.invalid = true;
            }
            return;
        }
        if self.mode == Mode::Reset
            && self.probe
            && self.dropped
            && self.replacement.is_none()
            && Some(token) != self.target
            && Some(token) != self.marker
        {
            self.replacement = Some(token);
        } else {
            self.invalid = true;
        }
    }
    /// Called only after the real timer-next acquired its original Wait owner.
    pub fn accepted_next(&mut self, token: Token, waits: u32) -> bool {
        if self.invalid {
            return false;
        }
        if !self.probe && (self.next_live || Some(token) != self.target || waits == 0) {
            self.invalid = true;
            return false;
        }
        if self.probe {
            return false;
        }
        self.next_live = true;
        true
    }
    pub fn pending(&mut self, token: Token) {
        if Some(token) != self.target || !self.next_live || self.next_pending || self.target_stopped
        {
            self.invalid = true;
            return;
        }
        self.next_pending = true;
    }
    /// Called only after the real provider clock reaches the requested instant.
    pub fn hold_due(&mut self, token: Token) {
        if Some(token) != self.target
            || !self.next_live
            || !self.next_pending
            || self.target_stopped
            || self.held
        {
            self.invalid = true;
            return;
        }
        self.held = true;
    }
    pub fn timer_stop(&mut self, token: Token, waits: u32) {
        if self.invalid {
            return;
        }
        if Some(token) == self.target {
            if !self.held
                || !self.next_live
                || !self.next_pending
                || self.target_stopped
                || waits == 0
            {
                self.invalid = true;
                return;
            }
            self.target_stopped = true;
        } else if Some(token) == self.marker {
            if !self.probe
                || !self.dropped
                || self.marker_stopped
                || (self.mode == Mode::Reset && !self.replacement_stopped)
            {
                self.invalid = true;
                return;
            }
            self.marker_stopped = true;
        } else if Some(token) == self.replacement {
            if !self.dropped || self.replacement_stopped {
                self.invalid = true;
                return;
            }
            self.replacement_stopped = true;
        } else {
            self.invalid = true;
        }
    }
    /// The guest probe requires the fence match to equal the first stopped
    /// token; this state independently requires that stop to be the target.
    pub fn fence_probe(&mut self, waits: u32, timers: u32) -> bool {
        if self.invalid
            || !self.held
            || !self.next_live
            || !self.next_pending
            || !self.target_stopped
            || self.marker.is_none()
            || self.probe
            || waits == 0
            || timers != 2
        {
            self.invalid = true;
            return false;
        }
        self.probe = true;
        true
    }
    /// Called after the field containing the original real `TimerWait` dropped.
    pub fn original_dropped(&mut self, token: Token, returned: bool) {
        if Some(token) != self.target || !self.probe || !self.next_live || self.dropped || !returned
        {
            self.invalid = true;
            return;
        }
        self.next_live = false;
        self.dropped = true;
    }
    pub fn invalid(&self) -> bool {
        self.invalid
    }
    pub fn probed(&self) -> bool {
        self.probe
    }
    pub fn original_matches(&self, token: Token) -> bool {
        Some(token) == self.target && self.next_pending
    }
    pub fn complete(&self) -> bool {
        !self.invalid
            && self.held
            && self.target_stopped
            && self.probe
            && self.dropped
            && self.marker_stopped
            && (self.mode == Mode::Stop || self.replacement_stopped)
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    fn token(id: u64) -> Token {
        Token { generation: 1, id }
    }
    fn before_probe(mode: Mode) -> Witness {
        let mut w = Witness::new(mode, token(1));
        w.timer_start(token(10), token(1), false);
        assert!(w.accepted_next(token(10), 1));
        w.pending(token(10));
        w.hold_due(token(10));
        w.timer_stop(token(10), 1);
        w.timer_start(token(11), token(1), false);
        w
    }
    #[test]
    fn stop_needs_matched_probe_physical_drop_and_public_return_marker() {
        let mut w = before_probe(Mode::Stop);
        assert!(!w.complete());
        assert!(w.fence_probe(1, 2));
        w.original_dropped(token(10), true);
        w.timer_stop(token(11), 0);
        assert!(w.complete());
    }
    #[test]
    fn reset_needs_old_drop_before_replacement_admission() {
        let mut w = before_probe(Mode::Reset);
        assert!(w.fence_probe(1, 2));
        w.original_dropped(token(10), true);
        w.timer_start(token(12), token(1), false);
        w.timer_stop(token(12), 0);
        w.timer_stop(token(11), 0);
        assert!(w.complete());
    }
    #[test]
    fn old_path_cannot_qualify_by_returning_early_or_attempting_new_timer() {
        let mut stop = before_probe(Mode::Stop);
        stop.timer_stop(token(11), 1);
        assert!(!stop.complete());
        let mut reset = before_probe(Mode::Reset);
        reset.timer_start(token(12), token(1), false);
        assert!(!reset.complete());
    }
    #[test]
    fn a_foreign_next_before_probe_invalidates_the_only_token_inference() {
        let mut w = before_probe(Mode::Stop);
        assert!(!w.accepted_next(token(11), 2));
        assert!(!w.fence_probe(2, 2));
        assert!(!w.complete());
    }
    #[test]
    fn early_or_missing_pending_wrong_identity_or_wrong_counters_fail_closed() {
        let mut w = before_probe(Mode::Stop);
        assert!(!w.fence_probe(1, 1));
        let mut w = before_probe(Mode::Stop);
        assert!(!w.fence_probe(0, 2));
        let mut w = before_probe(Mode::Stop);
        assert!(w.fence_probe(1, 2));
        w.original_dropped(
            Token {
                generation: 2,
                id: 10,
            },
            true,
        );
        assert!(!w.complete());
        let mut w = Witness::new(Mode::Stop, token(1));
        w.timer_start(token(10), token(1), false);
        assert!(w.accepted_next(token(10), 1));
        w.hold_due(token(10));
        assert!(!w.complete());
    }
    #[test]
    fn refused_or_duplicate_probe_and_unreturned_drop_do_not_qualify() {
        let mut w = before_probe(Mode::Stop);
        assert!(w.fence_probe(1, 2));
        assert!(!w.fence_probe(1, 2));
        assert!(!w.complete());
        let mut w = before_probe(Mode::Stop);
        assert!(w.fence_probe(1, 2));
        w.original_dropped(token(10), false);
        assert!(!w.complete());
    }
    #[test]
    fn target_closed_before_due_hold_cannot_qualify() {
        let mut w = Witness::new(Mode::Stop, token(1));
        w.timer_start(token(10), token(1), false);
        assert!(w.accepted_next(token(10), 1));
        w.pending(token(10));
        w.timer_stop(token(10), 1);
        assert!(!w.complete());
    }
    #[test]
    fn reset_cannot_admit_replacement_before_original_drop_even_after_probe() {
        let mut w = before_probe(Mode::Reset);
        assert!(w.fence_probe(1, 2));
        w.timer_start(token(12), token(1), false);
        assert!(!w.complete());
    }
}
