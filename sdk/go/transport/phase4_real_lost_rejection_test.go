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

func lostRejectionSelector(t *testing.T) tx.CommandSelector {
	return tx.CommandSelector{Namespace: &tx.NamespaceSelector{Tenant: rejectionField(t, "LSF_401_TENANT"), Namespace: rejectionField(t, "LSF_401_NAMESPACE"), Incarnation: rejectionField(t, "LSF_401_INCARNATION")}, Operation: "update", ClientKey: "go-sdk-lost-rejection"}
}
func TestPhase4LostRejectionAgainstRealNode(t *testing.T) {
	if os.Getenv("LSF_401_LIVE") != "1" {
		t.Skip("requires separate node and response-blocking fault fixture")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	cancellation := os.Getenv("LSF_401_CANCEL_AFTER_DISPATCH") == "1"
	if cancellation {
		timer := time.AfterFunc(5*time.Second, cancel)
		defer timer.Stop()
	}
	config := transport.DefaultConfig("http://"+rejectionField(t, "LSF_401_ENDPOINT"), rejectionField(t, "LSF_401_TOKEN"))
	if cancellation {
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
	tenant, key, route, wall := rejectionField(t, "LSF_401_TENANT"), "go-sdk-lost-rejection", "transaction-java-aggregate", uint64(120000)
	current, selector := tx.CurrentProfile(), lostRejectionSelector(t)
	request := tx.InvokeCommandRequest{Profile: &current, Command: &selector, InputFormat: "lsf-wit-values-v1", ExpectedVersions: []tx.ExpectedVersion{{Key: []byte("aggregate/count"), Version: &version}}, Invocation: &profile.InvokeRequest{ActivationId: &key, Target: &profile.InvocationTarget{Tenant: tenant, Service: "examples/transaction-java-aggregate", Contract: "examples:transactional-aggregate/api@1.0.0", Function: "update", Route: &route}, Payload: []byte(`[{"delta":1,"reject":true}]`), MediaType: "application/vnd.latent.wit-values.v1+json", Budget: &profile.ResourceBudget{CpuFuel: 1000000000, MemoryBytes: 67108864, StateReadBytes: 4194304, StateWriteBytes: 2097152, EffectCount: 1, WallTimeLimitMillis: &wall}}}
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
			t.Fatalf("cancellation mismatch: category=%d outcome=%d dispatched=%t", failure.Transport.Category, failure.Transport.Outcome, failure.Transport.Dispatched)
		}
		fmt.Println("CANCELLED_DISPATCH_UNKNOWN")
	}
	fmt.Println("LOST_REJECTION_UNKNOWN")
}
func TestPhase4RecoverLostRejectionAgainstRealNode(t *testing.T) {
	if os.Getenv("LSF_401_LIVE") != "1" {
		t.Skip("requires original rejection and later state change")
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
	current, selector := tx.CurrentProfile(), lostRejectionSelector(t)
	tenant := rejectionField(t, "LSF_401_TENANT")
	response, err := client.LookupCommand(ctx, tx.LookupCommandRequest{Profile: &current, Command: &selector, AuthorizationPublication: &profile.PublicationRef{Tenant: tenant, Id: rejectionField(t, "LSF_401_PUBLICATION")}}, profile.CallOptions{})
	if err != nil {
		t.Fatalf("lookup: %v", err)
	}
	c := response.Value.Command
	if c == nil || c.Outcome != tx.CommandOutcomeRejected || !c.MetadataDurable || c.ApplicationStateCommitted || c.Commit != nil || c.BusinessRejection == nil {
		t.Fatal("original durable rejection missing")
	}
	fingerprint, err := hex.DecodeString(rejectionField(t, "LSF_401_ORIGINAL_FINGERPRINT"))
	if err != nil {
		t.Fatal("invalid fingerprint")
	}
	code, err := hex.DecodeString(rejectionField(t, "LSF_401_REJECTION_CODE"))
	if err != nil {
		t.Fatal("invalid code")
	}
	payload, err := hex.DecodeString(rejectionField(t, "LSF_401_REJECTION_PAYLOAD"))
	if err != nil {
		t.Fatal("invalid payload")
	}
	if c.CommandId != rejectionField(t, "LSF_401_ORIGINAL_ID") || c.AttemptId != rejectionField(t, "LSF_401_ORIGINAL_ATTEMPT") || !bytes.Equal(c.FingerprintSha256, fingerprint) || !bytes.Equal([]byte(c.BusinessRejection.Code), code) || !bytes.Equal(c.BusinessRejection.Payload, payload) {
		t.Fatal("recovered original differs")
	}
	fmt.Println("LOST_REJECTION_RECOVERED")
}

func TestPhase4ChangedInputConflictsWithOriginalRejection(t *testing.T) {
	if os.Getenv("LSF_401_LIVE") != "1" {
		t.Skip("requires an original durable rejection on a separate node")
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
	version, err := hex.DecodeString(rejectionField(t, "LSF_401_EXPECTED_VERSION_HEX"))
	if err != nil || len(version) == 0 {
		t.Fatal("invalid original version")
	}
	tenant, key, route, wall := rejectionField(t, "LSF_401_TENANT"), "go-sdk-lost-rejection", "transaction-java-aggregate", uint64(120000)
	current, selector := tx.CurrentProfile(), lostRejectionSelector(t)
	request := tx.InvokeCommandRequest{Profile: &current, Command: &selector, InputFormat: "lsf-wit-values-v1", ExpectedVersions: []tx.ExpectedVersion{{Key: []byte("aggregate/count"), Version: &version}}, Invocation: &profile.InvokeRequest{ActivationId: &key, Target: &profile.InvocationTarget{Tenant: tenant, Service: "examples/transaction-java-aggregate", Contract: "examples:transactional-aggregate/api@1.0.0", Function: "update", Route: &route}, Payload: []byte(`[{"delta":2,"reject":true}]`), MediaType: "application/vnd.latent.wit-values.v1+json", Budget: &profile.ResourceBudget{CpuFuel: 1000000000, MemoryBytes: 67108864, StateReadBytes: 4194304, StateWriteBytes: 2097152, EffectCount: 1, WallTimeLimitMillis: &wall}}}
	_, err = client.InvokeCommand(ctx, request, profile.CallOptions{})
	var failure *tx.ClientFailure
	if !errors.As(err, &failure) || failure.Transport == nil {
		t.Fatalf("expected dispatched conflicting-input refusal: %v", err)
	}
	if failure.Transport.GrpcStatus == nil || *failure.Transport.GrpcStatus != 6 || !failure.Transport.Dispatched {
		status := int32(-1)
		if failure.Transport.GrpcStatus != nil {
			status = *failure.Transport.GrpcStatus
		}
		t.Fatalf("conflicting-input refusal: category=%d grpc=%d dispatched=%t outcome=%d", failure.Transport.Category, status, failure.Transport.Dispatched, failure.Transport.Outcome)
	}
	if failure.Identity.Command == nil || failure.Identity.Command.ClientKey != key || failure.Observed != nil {
		t.Fatal("conflict did not retain original command identity")
	}
	fmt.Println("CHANGED_INPUT_CONFLICT")
}
