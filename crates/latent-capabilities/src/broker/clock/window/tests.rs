use super::*;
use latent_core::{BoxFuture, ErrorDetail, Metadata};

fn failure() -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::Unavailable,
        retryable: true,
        message: "not used for admission".into(),
        details: vec![ErrorDetail {
            kind: "admission.currentness".into(),
            fields: Metadata::from([("reason".into(), "admission-authority-busy".into())]),
        }],
    }
}

#[test]
fn only_the_exact_busy_constructor_can_wait() {
    assert!(busy(&failure()));
    let mut error = failure();
    error.retryable = false;
    assert!(!busy(&error));
    error = failure();
    error.code = PlatformErrorCode::ResourceExhausted;
    assert!(!busy(&error));
    error = failure();
    error.details[0].kind = "other".into();
    assert!(!busy(&error));
    error = failure();
    error.details[0]
        .fields
        .insert("extra".into(), "private".into());
    assert!(!busy(&error));
    error = failure();
    error.details.push(error.details[0].clone());
    assert!(!busy(&error));
    error = failure();
    error.details.clear();
    assert!(!busy(&error));
    for reason in [
        "admission-authority-poisoned",
        "admission-clock-lease-uncovered",
        "revoked",
        "busy",
    ] {
        error = failure();
        error.details[0]
            .fields
            .insert("reason".into(), reason.into());
        assert!(!busy(&error));
    }
}

struct Timer(Instant);
impl PreparationReadWait for Timer {
    fn now(&self) -> Instant {
        self.0
    }
    fn wait_until(&self, _: Instant) -> BoxFuture<'_, ()> {
        panic!("constructing a window cannot wait")
    }
}

#[test]
fn one_checked_window_never_extends_the_original_deadline() {
    let now = Instant::now();
    let timer = Timer(now);
    assert_eq!(
        Window::new(&timer, None).unwrap().until,
        now + Duration::from_secs(5)
    );
    assert_eq!(
        Window::new(&timer, Some(now + Duration::from_secs(1)))
            .unwrap()
            .until,
        now + Duration::from_secs(1)
    );
    assert_eq!(Window::new(&timer, Some(now)).unwrap().until, now);
}
