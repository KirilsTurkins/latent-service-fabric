// Private observer only. Fixed labels, bounded aliases and numeric callsites.
mod private_fetch_trace {
    use super::RuntimeToken;
    type Frame = (u32, Option<usize>, Option<usize>);
    struct State {
        aliases: Vec<(RuntimeToken, &'static str)>,
        sites: Vec<Vec<Frame>>,
        events: usize,
    }
    static STATE: std::sync::Mutex<State> = std::sync::Mutex::new(State {
        aliases: Vec::new(), sites: Vec::new(), events: 0,
    });
    std::thread_local! {
        static LAST: std::cell::RefCell<Vec<Frame>> = const { std::cell::RefCell::new(Vec::new()) };
    }
    pub fn capture(trace: wasmtime::WasmBacktrace) {
        LAST.with(|last| {
            *last.borrow_mut() = trace.frames().iter().take(8)
                .map(|f| (f.func_index(), f.func_offset(), f.module_offset())).collect();
        });
    }
    pub fn event(action: &'static str, kind: Option<&'static str>, token: Option<RuntimeToken>,
                 parent: Option<RuntimeToken>, counts: [u32; 7]) {
        if counts.iter().any(|n| *n > 8192) || counts.iter().map(|n| u64::from(*n)).sum::<u64>() > 8192 {
            return;
        }
        let Ok(mut state) = STATE.lock() else { return };
        if state.events >= 96 { return; }
        let existing = token.and_then(|t| state.aliases.iter().position(|(known, _)| *known == t));
        let kind = kind.or_else(|| existing.map(|i| state.aliases[i].1));
        let Some(kind @ ("task" | "queued-work")) = kind else { return };
        let owner = if let Some(i) = existing { i + 1 } else if let Some(token) = token {
            if action != "register" || state.aliases.len() >= 256 { return; }
            state.aliases.push((token, kind));
            state.aliases.len()
        } else { 0 };
        let parent = parent.and_then(|t| state.aliases.iter().position(|(known, _)| *known == t))
            .map_or(0, |i| i + 1);
        let frames = if matches!(action, "register" | "refused") {
            LAST.with(|last| last.borrow().clone())
        } else { Vec::new() };
        let site = if frames.is_empty() { 0 } else if let Some(i) = state.sites.iter().position(|s| *s == frames) {
            i + 1
        } else if state.sites.len() < 4 {
            state.sites.push(frames.clone());
            let site = state.sites.len();
            let frames: Vec<_> = frames.iter().map(|f| serde_json::json!({
                "functionIndex": f.0, "functionOffset": f.1, "moduleOffset": f.2,
            })).collect();
            eprintln!("LSF_FETCH_OWNER_SITE {}", serde_json::json!({"site": site, "frames": frames}));
            site
        } else { 0 };
        state.events += 1;
        eprintln!("LSF_FETCH_OWNER_EVENT {}", serde_json::json!({
            "sequence": state.events, "action": action, "kind": kind,
            "owner": owner, "parent": parent, "counts": counts, "site": site,
        }));
    }
}
