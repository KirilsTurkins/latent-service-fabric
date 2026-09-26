//! Authoritative generated interfaces, also used in application bindgen `with`
//! mappings. This module intentionally exposes only implemented ABI versions.
pub use latent::blob0_2_0::blob;
pub use latent::clock::{monotonic, wall};
pub use latent::context::context;
pub use latent::events::publisher as events;
pub use latent::http0_2_0::client as http;
pub use latent::http0_3_0::streaming;
pub use latent::log::log;
pub use latent::random::random;
pub use latent::secrets::reader as secrets;
pub use latent::service::invoke as service;
pub use latent::telemetry::custom as metrics;
use latent_component_bindings::blob_guest::latent;
