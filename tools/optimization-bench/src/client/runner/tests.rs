use super::*;

#[test]
fn exact_wire_deadline_accounts_for_millisecond_rounding() {
    let anchor = Anchor {
        instant: Instant::now(),
        unix_nanos: 1_700_000_000_000_700_000,
        uncertainty: 50,
    };
    let offer = anchor.offer("measured", 2, 100_000, 1).unwrap();
    assert_eq!(offer.absolute_deadline, 1_700_000_000_002);
    assert_eq!(offer.deadline, 1_100_000);
    assert_eq!(offer.quantization, 200_000);
    assert_eq!(
        u128::from(offer.absolute_deadline) * 1_000_000,
        anchor.unix_nanos + u128::from(offer.deadline) + u128::from(offer.quantization)
    );
    assert_eq!(offer.deadline, offer.scheduled + 1_000_000);
}

#[test]
fn late_arrivals_and_capacity_overflow_remain_distinct_offers() {
    assert_eq!(undispatched(5, 10, 2, 2), Some("client-overload"));
    assert_eq!(
        undispatched(10, 10, 2, 2),
        Some("client-deadline-before-dispatch")
    );
    assert_eq!(undispatched(5, 10, 1, 2), None);
    // Every scheduled ordinal is retained even when the producer is far behind.
    let counts = (0..8)
        .map(|index| undispatched(100, index + 10, 2, 2))
        .collect::<Vec<_>>();
    assert_eq!(counts, vec![Some("client-deadline-before-dispatch"); 8]);
}

#[test]
fn counts_include_undispatched_and_out_of_order_completions() {
    let plan = super::super::plan::tests::fixture();
    let anchor = Anchor {
        instant: Instant::now(),
        unix_nanos: 1_700_000_000_000_000_000,
        uncertainty: 0,
    };
    let mut first = anchor
        .offer("measured", 0, 10, 1)
        .unwrap()
        .row(&plan, "client-overload");
    first.completed_nanos = "15".into();
    let mut second = anchor
        .offer("measured", 1, 20, 1)
        .unwrap()
        .row(&plan, "success");
    second.dispatch_nanos = Some("21".into());
    second.completed_nanos = "40".into();
    second.rpc_received = true;
    let mut counts = Counts::default();
    counts.observe(&second);
    counts.observe(&first);
    let value = counts.value();
    assert_eq!(value["attempts"], "2");
    assert_eq!(value["undispatched"], "1");
    assert_eq!(value["received"], "1");
    assert_eq!(value["elapsed_nanos"], "30");
    assert_eq!(first.service, "alpha");
    assert_eq!(second.service, "beta");
}
