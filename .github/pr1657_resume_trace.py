"""Disposable closed-numeric scheduler trace; never qualification evidence."""
from pathlib import Path
import os
import runpy
import subprocess

runpy.run_path('.github/pr1657_completion_trace.py')
p = Path('crates/vendor/wasmtime/src/runtime/component/concurrent.rs')
s = p.read_text()

def once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new)

helper = '''
fn resume_diagnostic(stage: u32, a: u32, b: u32) {
    use std::sync::{OnceLock, atomic::{AtomicUsize, Ordering}};
    use std::time::Instant;
    static START: OnceLock<Instant> = OnceLock::new();
    static EVENTS: AtomicUsize = AtomicUsize::new(0);
    let ordinal = EVENTS.fetch_add(1, Ordering::Relaxed);
    if ordinal < 512 {
        let micros = START.get_or_init(Instant::now).elapsed().as_micros();
        eprintln!("LSF-RESUME:{ordinal}:{micros}:{stage}:{a}:{b}");
    }
}
'''
s = once(s, 'const BLOCKED: u32 = 0xffff_ffff;', 'const BLOCKED: u32 = 0xffff_ffff;\n' + helper)
s = once(s, '        Ok(ready)\n    }\n}\n\n/// Job to be run on a worker fiber.', '        resume_diagnostic(200, instance.index.as_u32(), u32::from(ready) | (u32::from(state.do_not_enter) << 1));\n        Ok(ready)\n    }\n}\n\n/// Job to be run on a worker fiber.')
s = once(s, '        log::trace!("enter {instance:?}");', '        resume_diagnostic(201, instance.index.as_u32(), 0);\n        log::trace!("enter {instance:?}");')
s = once(s, '        log::trace!("exit {instance:?}");', '        resume_diagnostic(202, instance.index.as_u32(), 0);\n        log::trace!("exit {instance:?}");')
s = once(s, '        log::trace!("handle work item {item:?}");', '''        resume_diagnostic(210, match &item {
            WorkItem::PushFuture(..) => 1, WorkItem::ResumeFiber(..) => 2,
            WorkItem::ResumeThread(..) => 3, WorkItem::GuestCall(..) => 4,
            WorkItem::WorkerFunction(..) => 5,
        }, 0);
        log::trace!("handle work item {item:?}");''')
s = once(s, '        log::trace!("set event for {self:?}: {event:?}");', '''        if let Waitable::Host(task) = self {
            resume_diagnostic(220, task.rep(), self.common(state)?.set.map_or(u32::MAX, |set| set.rep()));
        }
        log::trace!("set event for {self:?}: {event:?}");''')
s = once(s, '            if let Some((thread, mode)) = state.get_mut(set)?.waiting.pop_first() {', '''            if let Some((thread, mode)) = state.get_mut(set)?.waiting.pop_first() {
                resume_diagnostic(221, thread.task.rep(), thread.thread.rep());''')
s = once(s, '                    let old = state.get_mut(set)?.waiting.insert(', '''                    resume_diagnostic(222, set.rep(), thread.thread.rep());
                    let old = state.get_mut(set)?.waiting.insert(''')
s = once(s, '                    lower(store.as_context_mut(), result, false)?;', '''                    resume_diagnostic(230, task.rep(), u32::from(result.is_some()));
                    lower(store.as_context_mut(), result, false)?;
                    resume_diagnostic(231, task.rep(), 0);''')
s = once(s, '                let on_complete = worker.finish(result);', '''                resume_diagnostic(232, 0, u32::from(result.is_some()));
                let on_complete = worker.finish(result);''')
p.write_text(s)
p = Path('tools/rust_thread_http_sibling_node.py')
s = p.read_text()
s = once(s, "write_json(output / 'completion-stage-trace.json',", """resume = [line.decode('ascii') for line in bytes(node.buffers[1]).splitlines()
                      if re.fullmatch(rb'LSF-RESUME:[0-9]{1,3}:[0-9]{1,16}:[0-9]{3}:[0-9]{1,10}:[0-9]{1,10}', line)]
            write_json(output / 'resume-stage-trace.json',
                       {'markers': resume[:512], 'diagnosticOnly': True})
            write_json(output / 'completion-stage-trace.json',""")
p.write_text(s)
out = Path(os.environ['RUNNER_TEMP']) / 'pr1657-completion-trace'
(out / 'resume-source.patch').write_bytes(subprocess.check_output(['git', 'diff', '--binary']))
print('Closed numeric queue, callback exclusion, waitable delivery and lowering observations installed.')
