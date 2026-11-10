package transport_test

import (
	"context"
	"os"
	"reflect"
	"testing"
	"time"

	"latent.dev/sdk/go/profile"
	tx "latent.dev/sdk/go/transaction"
	"latent.dev/sdk/go/transport"
)

func TestPhase4CommittedCommandAgainstRealNode(t *testing.T) {
	if os.Getenv("LSF_401_LIVE") != "1" {
		t.Skip("requires an explicitly provisioned separate signed node and committed fixture")
	}
	required := func(name string) string {
		t.Helper()
		value := os.Getenv(name)
		if value == "" {
			t.Fatalf("missing live-node fixture field %s", name)
		}
		return value
	}
	tenant, key := required("LSF_401_TENANT"), required("LSF_401_COMMAND_KEY")
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	client, err := transport.New(ctx, transport.DefaultConfig("http://"+required("LSF_401_ENDPOINT"), required("LSF_401_TOKEN")))
	if err != nil {
		t.Fatalf("create bounded client: %v", err)
	}
	defer func() {
		if err := client.Close(); err != nil {
			t.Errorf("client failed to retire: %v", err)
		}
	}()
	current := tx.CurrentProfile()
	request := tx.LookupCommandRequest{Profile: &current, Command: &tx.CommandSelector{Namespace: &tx.NamespaceSelector{Tenant: tenant, Namespace: required("LSF_401_NAMESPACE"), Incarnation: required("LSF_401_INCARNATION")}, Operation: required("LSF_401_OPERATION"), ClientKey: key}, AuthorizationPublication: &profile.PublicationRef{Tenant: tenant, Id: required("LSF_401_PUBLICATION")}}
	first, err := client.LookupCommand(ctx, request, profile.CallOptions{})
	if err != nil {
		t.Fatalf("first lookup: %v", err)
	}
	second, err := client.LookupCommand(ctx, request, profile.CallOptions{})
	if err != nil {
		t.Fatalf("second lookup: %v", err)
	}
	a, b := first.Value.Command, second.Value.Command
	if a == nil || b == nil || a.Key == nil || a.Commit == nil {
		t.Fatal("original committed command missing")
	}
	if a.CommandId != required("LSF_401_COMMAND_ID") || a.AttemptId != required("LSF_401_ATTEMPT_ID") || a.Key.ClientKey != key || a.Outcome != tx.CommandOutcomeCommitted || !a.MetadataDurable || !a.ApplicationStateCommitted {
		t.Fatal("original committed command identity or outcome changed")
	}
	if a.CommandId != b.CommandId || a.AttemptId != b.AttemptId || a.Outcome != b.Outcome || !reflect.DeepEqual(a.Key, b.Key) || !reflect.DeepEqual(a.FingerprintSha256, b.FingerprintSha256) || !reflect.DeepEqual(a.Source, b.Source) || !reflect.DeepEqual(a.Commit, b.Commit) {
		t.Fatal("repeated lookup changed retained identity or receipt")
	}
}
