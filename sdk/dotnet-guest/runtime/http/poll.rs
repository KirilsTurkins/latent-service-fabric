//! One exact WASI pollable identity for closed streams, timers and HTTP.
use super::{
    exports::wasi::io,
    latent,
    pump::{self, Readiness},
    quota::Slot,
    timer::Timer,
};
use std::rc::Rc;

pub struct Pollable {
    source: Rc<dyn Readiness>,
    _slot: Slot,
}
struct Closed;
impl Readiness for Closed {
    fn ready(&self) -> bool {
        true
    }
}
impl Pollable {
    pub fn new(source: Rc<dyn Readiness>) -> io::poll::Pollable {
        let slot = Slot::new();
        io::poll::Pollable::new(Self {
            source,
            _slot: slot,
        })
    }
    pub fn closed() -> io::poll::Pollable {
        Self::new(Rc::new(Closed))
    }
    pub fn timer(nanos: u64, absolute: bool) -> io::poll::Pollable {
        let delay = if absolute {
            nanos.saturating_sub(latent::clock::monotonic::now_nanos())
        } else {
            nanos
        };
        Self::new(Timer::new(delay))
    }
    pub fn poll(inputs: Vec<io::poll::PollableBorrow<'_>>) -> Vec<u32> {
        assert!(
            !inputs.is_empty() && inputs.len() <= 64,
            "WASI poll input limit"
        );
        let sources: Vec<_> = inputs
            .iter()
            .map(|resource| resource.get::<Self>().source.clone())
            .collect();
        Self::wait(&sources)
    }
    fn wait(sources: &[Rc<dyn Readiness>]) -> Vec<u32> {
        // Closed streams require no runtime grant or canonical allocation.
        // This also allows an unadmitted upload's initial writable window.
        let ready: Vec<_> = sources
            .iter()
            .enumerate()
            .filter(|(_, source)| source.ready())
            .map(|(index, _)| index as u32)
            .collect();
        if !ready.is_empty() {
            return ready;
        }
        pump::Pump::current().poll(sources)
    }
}
impl io::poll::GuestPollable for Pollable {
    fn block(&self) {
        Self::wait(&[self.source.clone()]);
    }
}
