from pathlib import Path
import os, json, subprocess, urllib.request, base64, hashlib
root = Path.cwd()
paths = ('sdk/wasi-http-runtime/retirement.rs', 'sdk/wasi-http-runtime/state.rs', 'tools/toolchain-smoke/examples/rust_wasi_http_runtime.rs')
if os.environ.get('STORE_TESTED_SOURCE') == '1':
    expected = subprocess.check_output(['git', 'write-tree']).decode().strip()
    changed = subprocess.check_output(['git', 'diff', '--cached', '--name-only']).decode().splitlines()
    assert set(changed) == set(paths)
    prefix = 'https://api.github.com/repos/KirilsTurkins/latent-service-fabric/git/'
    def post(endpoint, value):
        request = urllib.request.Request(prefix + endpoint, json.dumps(value).encode(), method='POST', headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'], 'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json', 'X-GitHub-Api-Version': '2022-11-28'})
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    entries = []
    for name in paths:
        raw = (root / name).read_bytes()
        sha = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        blob = post('blobs', {'content': base64.b64encode(raw).decode(), 'encoding': 'base64'})
        assert blob['sha'] == sha
        entries.append({'path': name, 'mode': '100644', 'type': 'blob', 'sha': sha})
    tree = post('trees', {'base_tree': 'b45308aa4be494c749244d017d5cb43afb64c61f', 'tree': entries})
    assert tree['sha'] == expected
    commit = post('commits', {'message': 'fix(rust-http): retire completed EOF resources before admitting sequential requests', 'tree': expected, 'parents': ['27164664b222bc52c88371a2225d147b3f8c020e']})
    assert commit['tree']['sha'] == expected and [p['sha'] for p in commit['parents']] == ['27164664b222bc52c88371a2225d147b3f8c020e']
    out = Path(os.environ['RUNNER_TEMP']) / 'pr1657-retirement'
    (out / 'candidate.json').write_text(json.dumps({'commit': commit['sha'], 'tree': expected, 'files': entries, 'branchMoved': False}, indent=2) + '\n')
    with open(os.environ['GITHUB_ENV'], 'a') as stream:
        stream.write('EXPECTED_HEAD=' + commit['sha'] + '\n')
    print(json.dumps({'testedCandidateCommit': commit['sha'], 'tree': expected, 'branchMoved': False}))
    raise SystemExit

p = root / paths[1]
s = p.read_text(); a = s.index('        // Keep the exact pinned future'); b = s.index('\n    pub fn fail(', a)
s = s[:a] + '''        // Pending canonical work still needs explicit async-root cancellation.
        // Completed EOF resources retire before admitting the next request;
        // their Task must not remain charged until an unrelated held call ends.
        if self.admitted.get() {
            let retirement = super::retirement::Retirement::new(
                self.work.borrow_mut().take(),
                self.upload.borrow_mut().take(),
                self.body.borrow_mut().take(),
                (
                    self.request.borrow_mut().take(),
                    self.queued.borrow_mut().take(),
                    self.input.borrow_mut().take(),
                    self.response.borrow_mut().take(),
                    self.trailers.borrow_mut().take(),
                ),
                self.owner.borrow_mut().take(),
                self.slot.borrow_mut().take(),
            );
            retirement.retire(self.eof.get(), |retirement| {
                pump::Pump::retire(move || drop(retirement));
            });
        }
    }
''' + s[b:]
p.write_text(s)
p = root / paths[2]
s = p.read_text(); needle = '#[path = "../../../sdk/wasi-http-runtime/state.rs"]'
assert s.count(needle) == 1
p.write_text(s.replace(needle, '#[path = "../../../sdk/wasi-http-runtime/retirement.rs"]\nmod retirement;\n' + needle))
(root / paths[0]).write_text('''//! Physical payloads precede their original logical owner, including on unwind.
//! Only observed EOF with no pending future or upload can retire synchronously.
pub(crate) struct Retirement<W, U, B, D, O, S> {
    work: Option<W>,
    upload: Option<U>,
    _body: Option<B>,
    _buffers: D,
    _owner: Option<O>,
    _slot: Option<S>,
}
impl<W, U, B, D, O, S> Retirement<W, U, B, D, O, S> {
    pub(crate) fn new(work: Option<W>, upload: Option<U>, body: Option<B>, buffers: D, owner: Option<O>, slot: Option<S>) -> Self {
        Self { work, upload, _body: body, _buffers: buffers, _owner: owner, _slot: slot }
    }
    pub(crate) fn retire(self, eof: bool, defer: impl FnOnce(Self)) {
        if eof && self.work.is_none() && self.upload.is_none() {
            // Resource-drop is synchronous, unlike cancelling a live canonical
            // future. Any detached provider cleanup retains its own paid owner.
            drop(self);
        } else {
            defer(self);
        }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    use std::{cell::{Cell, RefCell}, rc::Rc};
    struct Owned {
        name: &'static str,
        live: Rc<Cell<usize>>,
        events: Rc<RefCell<Vec<&'static str>>>,
        panic: bool,
    }
    impl Drop for Owned {
        fn drop(&mut self) {
            assert!(self.live.get() > 0, "resource lost its original owner");
            self.events.borrow_mut().push(self.name);
            if self.name == "owner" { self.live.set(self.live.get() - 1); }
            assert!(!self.panic, "resource-drop-control");
        }
    }
    fn part(name: &'static str, live: &Rc<Cell<usize>>, events: &Rc<RefCell<Vec<&'static str>>>) -> Owned {
        Owned { name, live: live.clone(), events: events.clone(), panic: false }
    }
    type Pending = Retirement<Owned, Owned, Owned, Owned, Owned, ()>;
    #[test]
    fn completed_eof_retires_resources_before_owner_without_deferring() {
        let live = Rc::new(Cell::new(1));
        let events = Rc::new(RefCell::new(Vec::new()));
        Pending::new(None, None, Some(part("body", &live, &events)), part("buffers", &live, &events), Some(part("owner", &live, &events)), Some(()))
            .retire(true, |_| panic!("completed EOF must not retain its Task until root drain"));
        assert_eq!(live.get(), 0);
        assert_eq!(*events.borrow(), ["body", "buffers", "owner"]);
    }
    #[test]
    fn sequential_completed_requests_reuse_the_original_finite_owner_capacity() {
        let live = Rc::new(Cell::new(5)); // Five unrelated admitted Tasks.
        let events = Rc::new(RefCell::new(Vec::new()));
        live.set(live.get() + 1);
        let held = Pending::new(Some(part("held-work", &live, &events)), None, None, part("held-buffers", &live, &events), Some(part("owner", &live, &events)), Some(()));
        for _ in 0..32 {
            assert!(live.get() < 8, "original Task ceiling must admit the next sibling");
            live.set(live.get() + 1);
            Pending::new(None, None, Some(part("body", &live, &events)), part("buffers", &live, &events), Some(part("owner", &live, &events)), Some(()))
                .retire(true, |_| panic!("settled sibling was retained"));
            assert_eq!(live.get(), 6);
        }
        let mut deferred = None;
        held.retire(false, |value| deferred = Some(value));
        assert_eq!(live.get(), 6);
        assert!(!events.borrow().contains(&"held-work"));
        drop(deferred);
        assert_eq!(live.get(), 5);
    }
    #[test]
    fn pending_future_upload_or_missing_eof_cannot_take_the_early_path() {
        for (eof, work, upload) in [(false, false, false), (false, true, false), (true, true, false), (true, false, true)] {
            let live = Rc::new(Cell::new(1));
            let events = Rc::new(RefCell::new(Vec::new()));
            let mut deferred = None;
            Pending::new(work.then(|| part("future", &live, &events)), upload.then(|| part("upload", &live, &events)),
                Some(part("body", &live, &events)), part("buffers", &live, &events), Some(part("owner", &live, &events)), Some(()))
                .retire(eof, |value| deferred = Some(value));
            assert!(deferred.is_some());
            assert!(events.borrow().is_empty());
            assert_eq!(live.get(), 1);
            drop(deferred);
            assert_eq!(live.get(), 0);
            let expected: Vec<_> = work.then_some("future").into_iter().chain(upload.then_some("upload")).chain(["body", "buffers", "owner"]).collect();
            assert_eq!(*events.borrow(), expected);
        }
    }
    #[test]
    fn original_owner_survives_resource_destructor_unwind() {
        for eof in [false, true] {
            let live = Rc::new(Cell::new(1));
            let events = Rc::new(RefCell::new(Vec::new()));
            let mut body = part("body", &live, &events);
            body.panic = true;
            let retirement = Pending::new(None, None, Some(body), part("buffers", &live, &events), Some(part("owner", &live, &events)), Some(()));
            let outcome = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| retirement.retire(eof, drop)));
            assert!(outcome.is_err());
            assert_eq!(*events.borrow(), ["body", "buffers", "owner"]);
            assert_eq!(live.get(), 0);
        }
    }
}
''')
