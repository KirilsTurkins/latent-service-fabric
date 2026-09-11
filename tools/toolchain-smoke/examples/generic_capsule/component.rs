#![cfg(target_arch = "wasm32")]

use std::sync::atomic::{AtomicU32, Ordering};

wit_bindgen::generate!({
    path: "examples/generic_capsule",
    world: "tests:generic/service@0.1.0",
    generate_all,
});

use self::exports::tests::generic::{alternate, values};

static COUNTER: AtomicU32 = AtomicU32::new(0);

struct GenericCapsule;

impl values::Guest for GenericCapsule {
    fn identify() -> u32 {
        11
    }

    fn combine(left: i32, right: i32) -> i32 {
        left.saturating_add(right)
    }

    fn transform(mut value: values::Composite) -> values::Composite {
        value.numbers.count = value.numbers.count.saturating_add(1);
        value.bytes.reverse();
        value
    }

    fn checked(allowed: bool) -> Result<String, values::Selection> {
        if allowed {
            Ok("accepted".to_owned())
        } else {
            Err(values::Selection::Named("denied".to_owned()))
        }
    }

    fn nothing() {}

    fn unit_result(allowed: bool) -> Result<(), ()> {
        if allowed {
            Ok(())
        } else {
            Err(())
        }
    }

    fn bump() -> u32 {
        COUNTER.fetch_add(1, Ordering::Relaxed) + 1
    }

    fn trap() -> u32 {
        panic!("controlled generic fixture trap")
    }

    fn spin() -> u32 {
        let mut counter = 0_u64;
        loop {
            counter = counter.wrapping_add(1);
            std::hint::black_box(counter);
        }
    }

    fn grow() -> u32 {
        let mut chunks = Vec::new();
        loop {
            let mut chunk = vec![0_u8; 64 * 1024];
            chunk[0] = 1;
            chunks.push(chunk);
            std::hint::black_box(&chunks);
        }
    }
}

impl alternate::Guest for GenericCapsule {
    fn identify() -> u32 {
        22
    }
}

export!(GenericCapsule);
