package transport_test

import (
	"os"
	"strconv"
	"testing"

	"latent.dev/sdk/go/profile"
)

func phase4FixtureWallLimit(t *testing.T) uint64 {
	t.Helper()
	value, configured := os.LookupEnv("LSF_401_WALL_TIME_MILLIS")
	if !configured {
		return 120000
	}
	millis, err := strconv.ParseUint(value, 10, 64)
	if err != nil || millis == 0 || millis > 120000 || strconv.FormatUint(millis, 10) != value {
		t.Fatal("invalid fixture wall-time limit")
	}
	return millis
}

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
