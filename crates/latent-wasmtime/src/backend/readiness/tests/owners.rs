use std::future::Future;
use std::sync::Arc;
use std::task::{Context, Waker};

use latent_artifacts::ArtifactRepository;
use latent_core::PlatformError;

use super::fixture::{Fence, Fixture, Timer};
use crate::compiler::{Acquisition, Admission};

#[tokio::test(flavor = "current_thread", start_paused = true)]
async fn dropping_final_currentness_wait_releases_exact_warm_ready_pin() {
    let f = Fixture::new().await;
    let ready = f.ready().await;
    let handle = ready.descriptor().opaque_handle.clone();
    drop(ready);
    let jobs = f.backend.compiler_snapshot().jobs_started;
    let Acquisition::Ready(pin) = f
        .backend
        .shared
        .compiler
        .as_ref()
        .unwrap()
        .acquire(Admission {
            identity: None,
            handle,
            source_bytes: 1,
            metadata_bytes: 1,
            document_bytes: 0,
        })
        .unwrap()
    else {
        panic!("proven warm cache entry")
    };
    let fence = Fence::hold(&f.eligibility);
    let context = &f.backend.shared.preparation_context;
    let mut pending = Box::pin(async move {
        let window = super::super::wait::Window::new(Some(&Timer));
        window.check(|| context.check_runtime(&pin.runtime)).await?;
        Ok::<_, PlatformError>(pin)
    });
    assert!(pending
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_pending());
    assert_eq!(f.backend.compiler_snapshot().ready_preparations, 1);
    assert!(f.backend.compiler_snapshot().ready_compiled_image_bytes > 0);
    drop(pending);
    assert_eq!(f.backend.compiler_snapshot().jobs_started, jobs);
    f.idle();
    fence.release();
}

#[tokio::test(flavor = "current_thread", start_paused = true)]
async fn dropping_post_acquire_source_wait_releases_unstarted_job_and_document_capacity() {
    let f = Fixture::new().await;
    let source = Arc::clone(&f.repository)
        .owned_preparation_source()
        .unwrap();
    let identity = source
        .identity_selected(&f.key.release, f.key.publication.as_ref())
        .unwrap()
        .unwrap();
    let handle =
        crate::backend::preparation::authenticated_handle(&f.key, &identity, Some(&f.eligibility));
    let Acquisition::Waiting {
        future,
        owner: true,
    } = f
        .backend
        .shared
        .compiler
        .as_ref()
        .unwrap()
        .acquire(Admission {
            identity: None,
            handle,
            source_bytes: identity.component_bytes() as usize,
            metadata_bytes: 1,
            document_bytes: 0,
        })
        .unwrap()
    else {
        panic!("one unstarted cold reservation")
    };
    let fence = Fence::hold(&f.eligibility);
    let key = f.key.clone();
    let mut pending = Box::pin(async move {
        let window = super::super::wait::Window::new(Some(&Timer));
        let bounds = window
            .check(|| source.read_bounds_selected(&key.release, key.publication.as_ref()))
            .await?;
        future.reserve_documents(super::super::document_bytes(bounds)?)?;
        Ok::<(), PlatformError>(())
    });
    assert!(pending
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_pending());
    let retained = f.backend.compiler_snapshot();
    assert_eq!(retained.waiting_callers, 1);
    assert_eq!(retained.ready_preparations, 1);
    assert_eq!(retained.reserved_document_bytes, 0);
    assert_eq!(retained.jobs_started, 0);
    drop(pending);
    f.idle();
    assert_eq!(f.backend.compiler_snapshot().jobs_started, 0);
    fence.release();
}
