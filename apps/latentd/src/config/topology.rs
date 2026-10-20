//! Fixed standalone composition; no row scales with deployments or services.
pub(crate) const NODE_ROWS: usize = 13;
pub(crate) const ACTIVATION_ROWS: usize = 8;
pub(crate) const SERVICE_ROWS: usize = 3;
pub(crate) const CATALOG_ROWS: usize = 1;
pub(crate) const HTTP_ROWS: usize = 5;
pub(crate) const POLICY_ROWS: usize = 2;
pub(crate) const ROLLOUT_ROWS: usize = 2;
pub(crate) const CANARY_ROWS: usize = 4;

// The source arrays use these same lengths, so adding a fixed row requires
// updating its precharged standalone capacity instead of silently truncating.
pub(crate) const MAXIMUM_ENTRIES: usize = NODE_ROWS
    + ACTIVATION_ROWS
    + SERVICE_ROWS
    + CATALOG_ROWS
    + HTTP_ROWS
    + POLICY_ROWS
    + ROLLOUT_ROWS
    + CANARY_ROWS;
