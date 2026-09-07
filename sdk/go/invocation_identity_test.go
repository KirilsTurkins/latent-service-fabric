package latent_test

import (
	"context"
	"errors"
	"reflect"
	"testing"

	latent "latent.dev/sdk/go"
)

func TestKnownIDAllowsStatusAndAllCancelDispositionsBeforeCompletion(t *testing.T) {
	f := newFixture()
	request := request()
	id := *request.ActivationID
	done, _ := start(t, f, request)
	status := getStatus(t, f, id)
	if status.Phase != "running" || status.TerminalState != nil {
		t.Fatalf("expected running nonterminal status: %+v", status)
	}
	if f.root != id {
		t.Fatalf("implicit root = %q, want effective ID %q", f.root, id)
	}
	assertCancel(t, f, id, latent.CancelAccepted, nil)
	assertCancel(t, f, id, latent.CancelAccepted, nil)
	assertPending(t, done)
	if getStatus(t, f, id).TerminalState != nil {
		t.Fatal("accepted cancellation must not fabricate terminal status")
	}
	assertCancel(t, f, "unknown", latent.CancelNotFound, nil)
	f.finish(t, "cancelled", false)
	result := <-done
	if result.err != nil || result.outcome.PlatformFailure == nil {
		t.Fatalf("expected cancellation platform outcome, got %+v", result)
	}
	if result.outcome.PlatformFailure.Error.Code != "cancelled" || result.outcome.PlatformFailure.Receipt.ActivationID != id {
		t.Fatalf("incorrect cancellation receipt: %+v", result.outcome.PlatformFailure)
	}
	assertCancel(t, f, id, latent.CancelAlreadyTerminal, stringPointer("cancelled"))
}

func TestCancelTransportFailureIsNotADispositionOrTerminalOutcome(t *testing.T) {
	f := newFixture()
	request := request()
	id := *request.ActivationID
	done, _ := start(t, f, request)
	f.mu.Lock()
	f.failCancel = true
	f.mu.Unlock()
	response, err := f.Cancel(context.Background(), id, "stop")
	if err == nil || err.Error() != "cancel transport unavailable" {
		t.Fatalf("expected transport error, got %v", err)
	}
	if response.Disposition != "" || response.TerminalState != nil || f.cancellationRequested {
		t.Fatalf("transport error fabricated a cancellation response: %+v", response)
	}
	if getStatus(t, f, id).TerminalState != nil {
		t.Fatal("failed cancellation must not complete the activation")
	}
	assertPending(t, done)
	f.finish(t, "completed", false)
	result := <-done
	if result.err != nil || result.outcome.Success == nil {
		t.Fatalf("expected normal success after failed cancellation: %+v", result)
	}
}

func TestLostResponseRecoversStatusByOriginalIDWithoutReinvoking(t *testing.T) {
	f := newFixture()
	request := request()
	id := *request.ActivationID
	done, _ := start(t, f, request)
	f.finish(t, "completed", true)
	result := <-done
	if result.err == nil || result.err.Error() != "invocation response lost" || result.outcome.Success != nil || result.outcome.DeclaredError != nil || result.outcome.PlatformFailure != nil {
		t.Fatalf("expected lost-response error: %+v", result)
	}
	status := getStatus(t, f, id)
	if status.TerminalState == nil || *status.TerminalState != "completed" || status.TerminalOutcome == nil || status.TerminalOutcome.Succeeded == nil {
		t.Fatalf("missing retained success after lost response: %+v", status)
	}
	if status.FinalConsumption == nil || status.FinalConsumption.CPUFuel != 7 || status.TerminalAtUnixMS == nil || *status.TerminalAtUnixMS != 2 {
		t.Fatalf("missing retained terminal accounting: %+v", status)
	}
	if f.invokeCount != 1 {
		t.Fatalf("status recovery reinvoked %d times", f.invokeCount)
	}
}

func TestAbsentIdentityIsPreservedUntilFixtureServerAssignment(t *testing.T) {
	f := newFixture()
	request := request()
	request.ActivationID = nil
	done, _ := start(t, f, request)
	if !reflect.DeepEqual(f.observed, request) || f.root != serverID {
		t.Fatalf("absence or server-assigned root changed: %+v, root %q", f.observed, f.root)
	}
	f.finish(t, "completed", false)
	result := <-done
	if result.err != nil || result.outcome.Success == nil || result.outcome.Success.ActivationID != serverID {
		t.Fatalf("response lost server-assigned identity: %+v", result)
	}
}

func TestExplicitLineagePreservesCallerIdentity(t *testing.T) {
	f := newFixture()
	request := request()
	request.RootActivationID = stringPointer("caller-root")
	request.ParentActivationID = stringPointer("caller-parent")
	done, _ := start(t, f, request)
	if !reflect.DeepEqual(f.observed, request) || f.root != *request.RootActivationID {
		t.Fatalf("lineage changed before server validation: %+v", f.observed)
	}
	f.finish(t, "completed", false)
	result := <-done
	if result.err != nil || result.outcome.Success == nil || result.outcome.Success.ActivationID != *request.ActivationID {
		t.Fatalf("caller identity replaced by lineage: %+v", result)
	}
}

func TestInvalidIdentityPresenceReachesServerValidationUnchanged(t *testing.T) {
	for _, field := range []string{"activation", "root", "parent", "parent-without-root"} {
		t.Run(field, func(t *testing.T) {
			f := newFixture()
			request := request()
			switch field {
			case "activation":
				request.ActivationID = stringPointer("")
			case "root":
				request.RootActivationID = stringPointer("")
			case "parent":
				request.RootActivationID = stringPointer("root")
				request.ParentActivationID = stringPointer("")
			case "parent-without-root":
				request.ParentActivationID = stringPointer("parent")
			}
			var client latent.Client = f
			_, err := client.Invoke(context.Background(), request)
			if err == nil || err.Error() != "invalid invocation identity" {
				t.Fatalf("expected server validation error, got %v", err)
			}
			if !reflect.DeepEqual(f.observed, request) || f.status != nil {
				t.Fatalf("invalid identity was normalized or admitted: %+v", f.observed)
			}
		})
	}
}

func TestCancellingLocalWaitDoesNotProveServerActivationStopped(t *testing.T) {
	f := newFixture()
	request := request()
	id := *request.ActivationID
	done, cancel := start(t, f, request)
	cancel()
	if result := <-done; !errors.Is(result.err, context.Canceled) {
		t.Fatalf("expected local context cancellation, got %+v", result)
	}
	if getStatus(t, f, id).TerminalState != nil {
		t.Fatal("local cancellation must not prove server completion")
	}
	assertCancel(t, f, id, latent.CancelAccepted, nil)
	f.finish(t, "cancelled", false)
	status := getStatus(t, f, id)
	if status.TerminalState == nil || *status.TerminalState != "cancelled" || f.invokeCount != 1 {
		t.Fatalf("incorrect retained status or implicit reinvocation: %+v", status)
	}
}
