package transport_test

import (
	"bytes"
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

func lostSelector(t *testing.T) tx.CommandSelector {
	return tx.CommandSelector{Namespace: &tx.NamespaceSelector{Tenant: rejectionField(t, "LSF_401_TENANT"), Namespace: rejectionField(t, "LSF_401_NAMESPACE"), Incarnation: rejectionField(t, "LSF_401_INCARNATION")}, Operation: "update", ClientKey: "go-sdk-lost-response"}
}
func TestPhase4LostCommittedResponseAgainstRealNode(t *testing.T) {
	if os.Getenv("LSF_401_LIVE") != "1" {
		t.Skip("requires separate node and response-blocking fault fixture")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	config := transport.DefaultConfig("http://"+rejectionField(t, "LSF_401_ENDPOINT"), rejectionField(t, "LSF_401_TOKEN"))
	if os.Getenv("LSF_401_CANCEL_AFTER_DISPATCH") == "1" {
		config.DefaultTimeout = 15 * time.Second
	}
	client, err := transport.New(ctx, config)
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
		t.Fatal("invalid version")
	}
	tenant, key, route, wall := rejectionField(t, "LSF_401_TENANT"), "go-sdk-lost-response", "transaction-java-aggregate", uint64(120000)
	current, selector := tx.CurrentProfile(), lostSelector(t)
	request := tx.InvokeCommandRequest{Profile: &current, Command: &selector, InputFormat: "lsf-wit-values-v1", ExpectedVersions: []tx.ExpectedVersion{{Key: []byte("aggregate/count"), Version: &version}}, Invocation: &profile.InvokeRequest{ActivationId: &key, Target: &profile.InvocationTarget{Tenant: tenant, Service: "examples/transaction-java-aggregate", Contract: "examples:transactional-aggregate/api@1.0.0", Function: "update", Route: &route}, Payload: []byte(`[{"delta":1,"reject":false}]`), MediaType: "application/vnd.latent.wit-values.v1+json", Budget: &profile.ResourceBudget{CpuFuel: 1000000000, MemoryBytes: 67108864, StateReadBytes: 4194304, StateWriteBytes: 2097152, EffectCount: 1, WallTimeLimitMillis: &wall}}}
	cancellation := os.Getenv("LSF_401_CANCEL_AFTER_DISPATCH") == "1"
	if cancellation {
		timer := time.AfterFunc(5*time.Second, cancel)
		defer timer.Stop()
	}
	_, err = client.InvokeCommand(ctx, request, profile.CallOptions{})
	if err == nil {
		t.Fatal("response-blocked call unexpectedly succeeded")
	}
	var failure *tx.ClientFailure
	if !errors.As(err, &failure) || failure.Transport == nil || !failure.Transport.Dispatched || failure.Transport.Outcome != profile.OutcomeKnowledgeUnknown {
		t.Fatalf("expected dispatched unknown outcome: %v", err)
	}
	if failure.Identity.Command == nil || failure.Identity.Command.ClientKey != key || failure.Observed != nil {
		t.Fatal("original identity missing or durable outcome fabricated")
	}
	if cancellation {
		if !errors.Is(err, context.Canceled) {
			t.Fatal("expected caller cancellation after dispatch")
		}
		fmt.Println("CANCELLED_COMMIT_UNKNOWN")
	}
	fmt.Println("LOST_RESPONSE_UNKNOWN")
}
func TestPhase4RecoverLostCommitAgainstRealNode(t *testing.T) {
	if os.Getenv("LSF_401_LIVE") != "1" {
		t.Skip("requires original commit and fresh node connection")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
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
	current, selector := tx.CurrentProfile(), lostSelector(t)
	tenant := rejectionField(t, "LSF_401_TENANT")
	response, err := client.LookupCommand(ctx, tx.LookupCommandRequest{Profile: &current, Command: &selector, AuthorizationPublication: &profile.PublicationRef{Tenant: tenant, Id: rejectionField(t, "LSF_401_PUBLICATION")}}, profile.CallOptions{})
	if err != nil {
		t.Fatalf("lookup: %v", err)
	}
	c := response.Value.Command
	if c == nil || c.Outcome != tx.CommandOutcomeCommitted || !c.MetadataDurable || !c.ApplicationStateCommitted || c.Commit == nil || len(c.Commit.EffectIds) != 1 {
		t.Fatal("original durable commit missing")
	}
	fingerprint, err := hex.DecodeString(rejectionField(t, "LSF_401_ORIGINAL_FINGERPRINT"))
	if err != nil {
		t.Fatal("invalid fingerprint")
	}
	if c.CommandId != rejectionField(t, "LSF_401_ORIGINAL_ID") || c.AttemptId != rejectionField(t, "LSF_401_ORIGINAL_ATTEMPT") || !bytes.Equal(c.FingerprintSha256, fingerprint) || c.Commit.ReceiptId != rejectionField(t, "LSF_401_ORIGINAL_RECEIPT") || c.Commit.EffectIds[0] != rejectionField(t, "LSF_401_ORIGINAL_EFFECT") {
		t.Fatal("recovered original differs")
	}
	fmt.Println("LOST_COMMIT_RECOVERED")
}
