package transport_test

import (
	"context"
	"errors"
	"fmt"
	"os"
	"testing"
	"time"

	"latent.dev/sdk/go/profile"
	tx "latent.dev/sdk/go/transaction"
	"latent.dev/sdk/go/transport"
)

func TestPhase4ForeignCallerCannotRecoverOriginal(t *testing.T) {
	if os.Getenv("LSF_401_LIVE") != "1" {
		t.Skip("requires a separate node, original command and foreign caller")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	client, err := transport.New(ctx, transport.DefaultConfig("http://"+rejectionField(t, "LSF_401_ENDPOINT"), rejectionField(t, "LSF_401_SCOPE_TOKEN")))
	if err != nil {
		t.Fatalf("client: %v", err)
	}
	defer func() {
		if err := client.Close(); err != nil {
			t.Error("client retirement")
		}
	}()
	current := tx.CurrentProfile()
	tenant := rejectionField(t, "LSF_401_TENANT")
	selector := tx.CommandSelector{Namespace: &tx.NamespaceSelector{Tenant: tenant, Namespace: rejectionField(t, "LSF_401_NAMESPACE"), Incarnation: rejectionField(t, "LSF_401_INCARNATION")}, Operation: "update", ClientKey: rejectionField(t, "LSF_401_COMMAND_KEY")}
	_, err = client.LookupCommand(ctx, tx.LookupCommandRequest{Profile: &current, Command: &selector, AuthorizationPublication: &profile.PublicationRef{Tenant: tenant, Id: rejectionField(t, "LSF_401_PUBLICATION")}}, profile.CallOptions{})
	if err == nil {
		t.Fatal("foreign caller recovered original")
	}
	var failure *tx.ClientFailure
	if !errors.As(err, &failure) || failure.Transport == nil || failure.Observed != nil {
		t.Fatalf("expected redacted transaction failure: %v", err)
	}
	if failure.Transport.GrpcStatus == nil || (*failure.Transport.GrpcStatus != 7 && *failure.Transport.GrpcStatus != 5) {
		t.Fatalf("unexpected scope refusal status")
	}
	fmt.Printf("SCOPE_REFUSED grpc=%d\n", *failure.Transport.GrpcStatus)
}
