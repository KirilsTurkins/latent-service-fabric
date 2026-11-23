package transport_test

import (
	"os"

	"latent.dev/sdk/go/profile"
)

func phase4AggregateTarget(tenant, function string) *profile.InvocationTarget {
	service, configured := os.LookupEnv("LSF_401_AGGREGATE_SERVICE")
	if !configured {
		service = "examples/transaction-java-aggregate"
	}
	route, configured := os.LookupEnv("LSF_401_AGGREGATE_ROUTE")
	if !configured {
		route = "transaction-java-aggregate"
	}
	if function == "query" {
		if selected, ok := os.LookupEnv("LSF_401_AGGREGATE_QUERY_ROUTE"); ok {
			route = selected
		}
	}
	return &profile.InvocationTarget{
		Tenant: tenant, Service: service, Contract: "examples:transactional-aggregate/api@1.0.0",
		Function: function, Route: &route,
	}
}
