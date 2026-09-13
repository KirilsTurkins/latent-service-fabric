use super::{
    invalid, StructuralCompatibility as Level, StructuralIssue, StructuralIssueCode,
    StructuralReport,
};
use latent_core::{PlatformError, PlatformErrorCode};

/// Defaults are hard maxima; a caller may only lower nonzero limits.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ComparisonLimits {
    pub max_nodes: usize,
    pub max_edges: usize,
    pub max_depth: usize,
    pub max_string_bytes: usize,
    pub max_name_bytes: usize,
    pub max_retained_bytes: usize,
    pub max_issues: usize,
    pub max_path_bytes: usize,
    pub max_report_bytes: usize,
}

impl Default for ComparisonLimits {
    fn default() -> Self {
        Self {
            max_nodes: 131_072,
            max_edges: 262_144,
            max_depth: 64,
            max_string_bytes: 8 * 1024 * 1024,
            max_name_bytes: 512,
            max_retained_bytes: 8 * 1024 * 1024,
            max_issues: 32,
            max_path_bytes: 1024,
            max_report_bytes: 64 * 1024,
        }
    }
}
impl ComparisonLimits {
    pub fn validate(self) -> Result<(), PlatformError> {
        let hard = Self::default();
        macro_rules! fields { ($($field:ident),+ $(,)?) => { $(
            if self.$field == 0 || self.$field > hard.$field { return Err(invalid()); }
        )+ }; }
        fields!(
            max_nodes,
            max_edges,
            max_depth,
            max_string_bytes,
            max_name_bytes,
            max_retained_bytes,
            max_issues,
            max_path_bytes,
            max_report_bytes
        );
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct ComparisonWork {
    pub nodes: usize,
    pub edges: usize,
    pub string_bytes: usize,
    pub retained_bytes: usize,
}

/// Shared accounting for package and descriptor analysis; this has no authority.
#[doc(hidden)]
pub struct Analysis {
    limits: ComparisonLimits,
    work: ComparisonWork,
    level: Level,
    complete: bool,
    truncated: bool,
    issues: Vec<StructuralIssue>,
    report_bytes: usize,
}
impl Analysis {
    pub fn new(limits: ComparisonLimits) -> Result<Self, PlatformError> {
        limits.validate()?;
        Ok(Self {
            limits,
            work: ComparisonWork::default(),
            level: Level::Identical,
            complete: true,
            truncated: false,
            issues: Vec::new(),
            report_bytes: 0,
        })
    }
    pub fn node(&mut self, depth: usize) -> Result<(), PlatformError> {
        if depth > self.limits.max_depth {
            return Err(exhausted());
        }
        charge(&mut self.work.nodes, 1, self.limits.max_nodes)
    }
    pub fn edge(&mut self, count: usize) -> Result<(), PlatformError> {
        charge(&mut self.work.edges, count, self.limits.max_edges)
    }
    pub fn text(&mut self, text: &str) -> Result<(), PlatformError> {
        charge(
            &mut self.work.string_bytes,
            text.len(),
            self.limits.max_string_bytes,
        )
    }
    pub fn name(&mut self, name: &str) -> Result<(), PlatformError> {
        if name.is_empty() {
            return Err(invalid());
        }
        if name.len() > self.limits.max_name_bytes {
            return Err(exhausted());
        }
        self.text(name)
    }
    pub fn retained(&mut self, amount: usize) -> Result<(), PlatformError> {
        charge(
            &mut self.work.retained_bytes,
            amount,
            self.limits.max_retained_bytes,
        )
    }
    pub fn added(&mut self) {
        if self.level == Level::Identical {
            self.level = Level::BackwardCompatible;
        }
    }
    pub fn issue(&mut self, level: Level, code: StructuralIssueCode, path: &[&str]) {
        let rank = |value| match value {
            Level::Identical => 0,
            Level::BackwardCompatible => 1,
            Level::Breaking => 2,
            Level::Unsupported => 3,
            Level::Unknown => 4,
        };
        if rank(level) > rank(self.level) {
            self.level = level;
        }
        if matches!(level, Level::Unsupported | Level::Unknown) {
            self.complete = false;
        }
        // Preallocate only a bounded exact path, never format an unbounded path first.
        if self.issues.len() >= self.limits.max_issues {
            self.truncated = true;
            return;
        }
        let mut bytes = 1usize;
        for part in path {
            bytes = bytes
                .saturating_add(1)
                .saturating_add(part.len())
                .min(self.limits.max_path_bytes);
        }
        let capacity = bytes.min(self.limits.max_path_bytes);
        let needed = capacity.saturating_add(std::mem::size_of::<StructuralIssue>());
        if self.report_bytes.saturating_add(needed) > self.limits.max_report_bytes {
            self.truncated = true;
            return;
        }
        let mut rendered = String::with_capacity(capacity);
        rendered.push('$');
        for part in path {
            if rendered.len() == capacity {
                self.truncated = true;
                break;
            }
            rendered.push('/');
            for ch in part.chars() {
                if rendered.len().saturating_add(ch.len_utf8()) > capacity {
                    self.truncated = true;
                    break;
                }
                rendered.push(ch);
            }
        }
        self.issues.reserve_exact(1);
        self.report_bytes = self.report_bytes.saturating_add(needed);
        self.issues.push(StructuralIssue {
            path: rendered.into_boxed_str(),
            code,
        });
    }
    pub fn exhausted(&mut self) {
        self.issue(Level::Unknown, StructuralIssueCode::AnalysisLimit, &[]);
    }
    #[must_use]
    pub fn finish(self) -> StructuralReport {
        StructuralReport {
            level: self.level,
            analysis_complete: self.complete,
            diagnostics_truncated: self.truncated,
            issues: self.issues.into_boxed_slice(),
            work: self.work,
        }
    }
}

fn charge(total: &mut usize, amount: usize, maximum: usize) -> Result<(), PlatformError> {
    *total = total
        .checked_add(amount)
        .filter(|n| *n <= maximum)
        .ok_or_else(exhausted)?;
    Ok(())
}
fn exhausted() -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::ResourceExhausted,
        message: "comparison-work-limit".to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}
