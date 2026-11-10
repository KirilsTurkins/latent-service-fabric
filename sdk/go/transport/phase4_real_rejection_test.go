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

func rejectionField(t *testing.T, name string) string {
	t.Helper()
	v := os.Getenv(name)
	if v == "" {
		t.Fatalf("missing fixture field %s", name)
	}
	return v
}
func rejectionSelector(t *testing.T) tx.CommandSelector {
	return tx.CommandSelector{Namespace: &tx.NamespaceSelector{Tenant: rejectionField(t, "LSF_401_TENANT"), Namespace: rejectionField(t, "LSF_401_NAMESPACE"), Incarnation: rejectionField(t, "LSF_401_INCARNATION")}, Operation: "update", ClientKey: "go-sdk-rejected-command"}
}
func rejectionClient(t *testing.T, ctx context.Context) *transport.Client {
	t.Helper()
	c, e := transport.New(ctx, transport.DefaultConfig("http://"+rejectionField(t, "LSF_401_ENDPOINT"), rejectionField(t, "LSF_401_TOKEN")))
	if e != nil {
		t.Fatalf("client: %v", e)
	}
	return c
}
func TestPhase4RejectAgainstRealNode(t *testing.T) {
	if os.Getenv("LSF_401_LIVE") != "1" {
		t.Skip("requires a separate signed node and current key version")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	client := rejectionClient(t, ctx)
	defer func() {
		if e := client.Close(); e != nil {
			t.Error("client retirement")
		}
	}()
	version, e := hex.DecodeString(rejectionField(t, "LSF_401_EXPECTED_VERSION_HEX"))
	if e != nil || len(version) == 0 {
		t.Fatal("invalid version")
	}
	tenant, key, route, wall := rejectionField(t, "LSF_401_TENANT"), "go-sdk-rejected-command", "transaction-java-aggregate", uint64(120000)
	current, selector := tx.CurrentProfile(), rejectionSelector(t)
	request := tx.InvokeCommandRequest{Profile: &current, Command: &selector, InputFormat: "lsf-wit-values-v1", ExpectedVersions: []tx.ExpectedVersion{{Key: []byte("aggregate/count"), Version: &version}}, Invocation: &profile.InvokeRequest{ActivationId: &key, Target: &profile.InvocationTarget{Tenant: tenant, Service: "examples/transaction-java-aggregate", Contract: "examples:transactional-aggregate/api@1.0.0", Function: "update", Route: &route}, Payload: []byte(`[{"delta":1,"reject":true}]`), MediaType: "application/vnd.latent.wit-values.v1+json", Budget: &profile.ResourceBudget{CpuFuel: 1000000000, MemoryBytes: 67108864, StateReadBytes: 4194304, StateWriteBytes: 2097152, EffectCount: 1, WallTimeLimitMillis: &wall}}}
	response, e := client.InvokeCommand(ctx, request, profile.CallOptions{})
	if e != nil {
		t.Fatalf("rejection invocation: %v", e)
	}
	c, i := response.Value.Command, response.Value.Invocation
	if c == nil || i == nil || i.DeclaredError == nil || c.Outcome != tx.CommandOutcomeRejected || !c.MetadataDurable || c.ApplicationStateCommitted || c.Commit != nil || i.DeclaredError.Code == "" || len(i.DeclaredError.Payload) == 0 {
		t.Fatal("durable rejection missing")
	}
	fmt.Printf("REJECTION %s %s %x %x %x\n", c.CommandId, c.AttemptId, c.FingerprintSha256, []byte(i.DeclaredError.Code), i.DeclaredError.Payload)
}
func TestPhase4RecoverRejectionAgainstRealNode(t *testing.T) {
	if os.Getenv("LSF_401_LIVE") != "1" {
		t.Skip("requires original rejection and later committed state change")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	client := rejectionClient(t, ctx)
	defer func() {
		if e := client.Close(); e != nil {
			t.Error("client retirement")
		}
	}()
	current, selector := tx.CurrentProfile(), rejectionSelector(t)
	tenant := rejectionField(t, "LSF_401_TENANT")
	response, e := client.LookupCommand(ctx, tx.LookupCommandRequest{Profile: &current, Command: &selector, AuthorizationPublication: &profile.PublicationRef{Tenant: tenant, Id: rejectionField(t, "LSF_401_PUBLICATION")}}, profile.CallOptions{})
	if e != nil {
		t.Fatalf("lookup: %v", e)
	}
	c := response.Value.Command
	if c == nil || c.BusinessRejection == nil || c.Outcome != tx.CommandOutcomeRejected || !c.MetadataDurable || c.ApplicationStateCommitted || c.Commit != nil {
		t.Fatal("original rejection missing")
	}
	fingerprint, e := hex.DecodeString(rejectionField(t, "LSF_401_REJECTION_FINGERPRINT"))
	if e != nil {
		t.Fatal("invalid fingerprint")
	}
	code, e := hex.DecodeString(rejectionField(t, "LSF_401_REJECTION_CODE"))
	if e != nil {
		t.Fatal("invalid code")
	}
	payload, e := hex.DecodeString(rejectionField(t, "LSF_401_REJECTION_PAYLOAD"))
	if e != nil {
		t.Fatal("invalid payload")
	}
	if c.CommandId != rejectionField(t, "LSF_401_REJECTION_ID") || c.AttemptId != rejectionField(t, "LSF_401_REJECTION_ATTEMPT") || !bytes.Equal(c.FingerprintSha256, fingerprint) || !bytes.Equal([]byte(c.BusinessRejection.Code), code) || !bytes.Equal(c.BusinessRejection.Payload, payload) {
		t.Fatal("recovered rejection differs")
	}
	fmt.Println("REJECTION_RECOVERED")
}
