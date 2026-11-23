use latent_sdk::management::InvocationTarget;

pub fn target(tenant: String, function: &str) -> InvocationTarget {
    let service = setting("LSF_401_AGGREGATE_SERVICE")
        .unwrap_or_else(|| "examples/transaction-java-aggregate".into());
    let query_route = (function == "query")
        .then(|| setting("LSF_401_AGGREGATE_QUERY_ROUTE"))
        .flatten();
    let route = query_route
        .or_else(|| setting("LSF_401_AGGREGATE_ROUTE"))
        .unwrap_or_else(|| "transaction-java-aggregate".into());
    InvocationTarget {
        tenant,
        service,
        contract: "examples:transactional-aggregate/api@1.0.0".into(),
        function: function.into(),
        route: Some(route),
    }
}

fn setting(name: &str) -> Option<String> {
    std::env::var_os(name).map(|value| value.into_string().expect("aggregate setting is UTF-8"))
}
