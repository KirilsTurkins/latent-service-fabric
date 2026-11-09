package transport_test

import (
	"bytes"
	"context"
	"encoding/hex"
	"fmt"
	"os"
	"testing"
	"time"

	"latent.dev/sdk/go/profile"
	tx "latent.dev/sdk/go/transaction"
	"latent.dev/sdk/go/transport"
)

func TestPhase4StaleEditAgainstRealNode(t *testing.T) {
	if os.Getenv("LSF_401_LIVE") != "1" {
		t.Skip("requires an original view and a newer committed state")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	client, err := transport.New(ctx, transport.DefaultConfig("http://"+rejectionField(t, "LSF_401_ENDPOINT"), rejectionField(t, "LSF_401_TOKEN")))
	if err != nil {
		t.Fatalf("client: %v", err)
	}
	defer func() {
		if err := client.Close(); err != nil {
			t.Error("client retirement")
		}
	}()
	version, err := hex.DecodeString(rejectionField(t, "LSF_401_EXPECTED_VERSION_HEX"))
	if err != nil || len(version) == 0 {
		t.Fatal("original version")
	}
	key, tenant, route, wall := "go-sdk-stale-edit", rejectionField(t, "LSF_401_TENANT"), "transaction-java-aggregate", uint64(120000)
	current := tx.CurrentProfile()
	selector := tx.CommandSelector{Namespace: &tx.NamespaceSelector{Tenant: tenant, Namespace: rejectionField(t, "LSF_401_NAMESPACE"), Incarnation: rejectionField(t, "LSF_401_INCARNATION")}, Operation: "update", ClientKey: key}
	req := tx.InvokeCommandRequest{Profile: &current, Command: &selector, InputFormat: "lsf-wit-values-v1", ExpectedVersions: []tx.ExpectedVersion{{Key: []byte("aggregate/count"), Version: &version}}, Invocation: &profile.InvokeRequest{ActivationId: &key, Target: &profile.InvocationTarget{Tenant: tenant, Service: "examples/transaction-java-aggregate", Contract: "examples:transactional-aggregate/api@1.0.0", Function: "update", Route: &route}, Payload: []byte(`[{"delta":1,"reject":false}]`), MediaType: "application/vnd.latent.wit-values.v1+json", Budget: &profile.ResourceBudget{CpuFuel: 1000000000, MemoryBytes: 67108864, StateReadBytes: 4194304, StateWriteBytes: 2097152, EffectCount: 1, WallTimeLimitMillis: &wall}}}
	result, err := client.InvokeCommand(ctx, req, profile.CallOptions{})
	if err != nil {
		t.Fatalf("stale edit response: %v", err)
	}
	retained := result.Metadata.Identity.ExpectedVersions
	if len(retained) != 1 || retained[0].Version == nil || !bytes.Equal(*retained[0].Version, version) {
		t.Fatal("original version replaced")
	}
	c := result.Value.Command
	if c == nil || c.Outcome != tx.CommandOutcomeAborted || !c.MetadataDurable || c.ApplicationStateCommitted || c.Commit != nil || c.ProvenAbort == nil {
		t.Fatal("durable abort missing")
	}
	fmt.Println("GO_STALE_EDIT_ABORTED")
}
