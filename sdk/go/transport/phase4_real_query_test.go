package transport_test

import (
	"bytes"
	"context"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"testing"
	"time"

	"latent.dev/sdk/go/profile"
	tx "latent.dev/sdk/go/transaction"
	"latent.dev/sdk/go/transport"
)

func TestPhase4FreshQueryAfterCommitAgainstRealNode(t *testing.T) {
	if os.Getenv("LSF_401_LIVE") != "1" {
		t.Skip("requires separate node and a known committed state")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	tenant := rejectionField(t, "LSF_401_TENANT")
	cfg := transport.DefaultConfig("http://"+rejectionField(t, "LSF_401_ENDPOINT"), rejectionField(t, "LSF_401_TOKEN"))
	client, err := transport.New(ctx, cfg)
	if err != nil {
		t.Fatalf("client: %v", err)
	}
	defer func() {
		if err := client.Close(); err != nil {
			t.Error("client retirement")
		}
	}()
	minimum, err := hex.DecodeString(rejectionField(t, "LSF_401_QUERY_MINIMUM_HEX"))
	if err != nil || len(minimum) == 0 {
		t.Fatal("invalid minimum view")
	}
	expected := minimum
	if raw := os.Getenv("LSF_401_QUERY_EXPECTED_HEX"); raw != "" {
		expected, err = hex.DecodeString(raw)
		if err != nil || len(expected) == 0 {
			t.Fatal("invalid expected view")
		}
	}
	key, route, wall := "go-sdk-fresh-query", "transaction-java-aggregate", uint64(120000)
	current := tx.CurrentProfile()
	ns := tx.NamespaceSelector{Tenant: tenant, Namespace: rejectionField(t, "LSF_401_NAMESPACE"), Incarnation: rejectionField(t, "LSF_401_INCARNATION")}
	query := tx.QueryRequest{Profile: &current, Namespace: &ns, MinimumViewVersion: &minimum, Invocation: &profile.InvokeRequest{
		ActivationId: &key, Target: &profile.InvocationTarget{Tenant: tenant, Service: "examples/transaction-java-aggregate", Contract: "examples:transactional-aggregate/api@1.0.0", Function: "query", Route: &route},
		Payload: []byte(`[]`), MediaType: "application/vnd.latent.wit-values.v1+json", Budget: &profile.ResourceBudget{CpuFuel: 1000000000, MemoryBytes: 67108864, StateReadBytes: 4194304, WallTimeLimitMillis: &wall},
	}}
	for i := 0; i < 3; i++ {
		activation := fmt.Sprintf("%s-%d", key, i)
		query.Invocation.ActivationId = &activation
		result, err := client.Query(ctx, query, profile.CallOptions{})
		if err != nil {
			t.Fatalf("fresh query: %v", err)
		}
		value := result.Value
		if result.Metadata.Observed != nil || value.Invocation == nil || value.Invocation.Success == nil || value.View == nil || value.View.Namespace == nil || value.Source == nil {
			t.Fatal("query outcome or view missing")
		}
		if value.View.Namespace.Tenant != tenant || value.View.Namespace.Namespace != ns.Namespace || value.View.Namespace.Incarnation != ns.Incarnation || !bytes.Equal(value.View.Version, expected) {
			t.Fatal("query scope or view changed")
		}
		if value.Invocation.Success.CommittedStateVersion != nil || len(value.Invocation.Success.EffectIds) != 0 {
			t.Fatal("query returned a mutation receipt")
		}
		var payload []struct {
			OK struct {
				Count       string `json:"count"`
				ViewVersion []int  `json:"view-version"`
			} `json:"ok"`
		}
		if json.Unmarshal(value.Invocation.Success.Payload, &payload) != nil || len(payload) != 1 || payload[0].OK.Count != "2" || len(payload[0].OK.ViewVersion) != len(value.View.Version) {
			t.Fatal("unexpected query value")
		}
		for j, octet := range payload[0].OK.ViewVersion {
			if octet < 0 || octet > 255 || byte(octet) != value.View.Version[j] {
				t.Fatal("query result and view token differ")
			}
		}
	}
	fmt.Println("FRESH_QUERY_AFTER_COMMIT")
}
