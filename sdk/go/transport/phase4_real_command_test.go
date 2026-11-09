package transport_test

import (
	"context"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"testing"
	"time"

	"latent.dev/sdk/go/profile"
	tx "latent.dev/sdk/go/transaction"
	"latent.dev/sdk/go/transport"
)

func TestPhase4CommandAgainstRealNode(t *testing.T) {
	if os.Getenv("LSF_401_LIVE") != "1" {
		t.Skip("requires an explicitly provisioned separate signed node and current key version")
	}
	required := func(name string) string {
		t.Helper()
		v := os.Getenv(name)
		if v == "" {
			t.Fatalf("missing fixture field %s", name)
		}
		return v
	}
	tenant := required("LSF_401_TENANT")
	version, err := hex.DecodeString(required("LSF_401_EXPECTED_VERSION_HEX"))
	if err != nil || len(version) == 0 {
		t.Fatal("invalid expected version")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	client, err := transport.New(ctx, transport.DefaultConfig("http://"+required("LSF_401_ENDPOINT"), required("LSF_401_TOKEN")))
	if err != nil {
		t.Fatalf("client: %v", err)
	}
	defer func() {
		if err := client.Close(); err != nil {
			t.Errorf("client retirement: %v", err)
		}
	}()
	current, activation, route, wall := tx.CurrentProfile(), "go-sdk-direct-command", "transaction-java-aggregate", uint64(120000)
	request := tx.InvokeCommandRequest{Profile: &current, Command: &tx.CommandSelector{Namespace: &tx.NamespaceSelector{Tenant: tenant, Namespace: required("LSF_401_NAMESPACE"), Incarnation: required("LSF_401_INCARNATION")}, Operation: "update", ClientKey: activation}, Invocation: &profile.InvokeRequest{ActivationId: &activation, Target: &profile.InvocationTarget{Tenant: tenant, Service: "examples/transaction-java-aggregate", Contract: "examples:transactional-aggregate/api@1.0.0", Function: "update", Route: &route}, Payload: []byte(`[{"delta":1,"reject":false}]`), MediaType: "application/vnd.latent.wit-values.v1+json", Budget: &profile.ResourceBudget{CpuFuel: 1000000000, MemoryBytes: 67108864, StateReadBytes: 4194304, StateWriteBytes: 2097152, EffectCount: 1, WallTimeLimitMillis: &wall}}, InputFormat: "lsf-wit-values-v1", ExpectedVersions: []tx.ExpectedVersion{{Key: []byte("aggregate/count"), Version: &version}}}
	response, err := client.InvokeCommand(ctx, request, profile.CallOptions{})
	if err != nil {
		var failure *tx.ClientFailure
		if errors.As(err, &failure) {
			t.Logf("DIAGNOSTIC category=%d outcome=%d dispatched=%t", failure.Transport.Category, failure.Transport.Outcome, failure.Transport.Dispatched)
		}
		recovery, recoveryErr := transport.New(ctx, transport.DefaultConfig("http://"+required("LSF_401_ENDPOINT"), required("LSF_401_TOKEN")))
		if recoveryErr == nil {
			original, lookupErr := recovery.LookupCommand(ctx, tx.LookupCommandRequest{Profile: &current, Command: request.Command, AuthorizationPublication: &profile.PublicationRef{Tenant: tenant, Id: required("LSF_401_PUBLICATION")}}, profile.CallOptions{})
			if lookupErr == nil && original.Value.Command != nil && original.Value.Command.Commit != nil {
				v := original.Value.Command
				t.Logf("RECOVERY outcome=%d durable=%t committed=%t effects=%d", v.Outcome, v.MetadataDurable, v.ApplicationStateCommitted, len(v.Commit.EffectIds))
			} else {
				t.Log("RECOVERY_FAILED")
			}
			if closeErr := recovery.Close(); closeErr != nil {
				t.Error("recovery owner retirement")
			}
		} else {
			t.Log("RECOVERY_CLIENT_FAILED")
		}
		t.Fatalf("original command invocation: %v", err)
	}
	result := response.Value.Command
	if result == nil || result.Outcome != tx.CommandOutcomeCommitted || !result.MetadataDurable || !result.ApplicationStateCommitted || result.Commit == nil || len(result.Commit.EffectIds) != 1 {
		t.Fatal("durable committed command and effect missing")
	}
	fmt.Printf("RESULT %s %s %s\n", result.CommandId, result.AttemptId, result.Commit.EffectIds[0])
}
