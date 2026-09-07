package latent_test

// This fixture server demonstrates the interface contract without implementing
// a transport, identity generator, or retry policy in the SDK.
import (
	"context"
	"errors"
	"sync"
	"testing"

	latent "latent.dev/sdk/go"
)

const serverID = "fixture-server-activation"

type invokeResult struct {
	outcome latent.InvocationOutcome
	err     error
}

type fixtureClient struct {
	mu                    sync.Mutex
	observed              latent.InvokeRequest
	root                  string
	status                *latent.ActivationStatus
	invokeCount           int
	cancellationRequested bool
	failCancel            bool
	started               chan struct{}
	response              chan invokeResult
}

var _ latent.Client = (*fixtureClient)(nil)

func newFixture() *fixtureClient {
	return &fixtureClient{
		started:  make(chan struct{}),
		response: make(chan invokeResult, 1),
	}
}

func stringPointer(value string) *string { return &value }

func request() latent.InvokeRequest {
	return latent.InvokeRequest{
		ActivationID: stringPointer("caller-activation"),
		Target: latent.Target{
			Tenant: "tenant", Service: "service", Contract: "contract", Function: "function",
		},
		MediaType: "text/plain",
	}
}

func (f *fixtureClient) begin(request latent.InvokeRequest) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.invokeCount++
	f.observed = request
	for _, id := range []*string{request.ActivationID, request.RootActivationID, request.ParentActivationID} {
		if id != nil && *id == "" {
			return errors.New("invalid invocation identity")
		}
	}
	if request.ParentActivationID != nil && request.RootActivationID == nil {
		return errors.New("invalid invocation identity")
	}
	id := serverID
	if request.ActivationID != nil {
		id = *request.ActivationID
	}
	f.root = id
	if request.RootActivationID != nil {
		f.root = *request.RootActivationID
	}
	f.status = &latent.ActivationStatus{
		ActivationID: id, Phase: "running", LastUpdatedUnixMS: 1,
	}
	return nil
}

func (f *fixtureClient) Invoke(ctx context.Context, request latent.InvokeRequest) (latent.InvocationOutcome, error) {
	err := f.begin(request)
	close(f.started)
	if err != nil {
		return latent.InvocationOutcome{}, err
	}
	select {
	case result := <-f.response:
		return result.outcome, result.err
	case <-ctx.Done():
		// Losing the local wait leaves the fixture server's activation intact.
		return latent.InvocationOutcome{}, ctx.Err()
	}
}

func (f *fixtureClient) Cancel(_ context.Context, activationID, _ string) (latent.CancelResponse, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.failCancel {
		return latent.CancelResponse{}, errors.New("cancel transport unavailable")
	}
	if f.status == nil || f.status.ActivationID != activationID {
		return latent.CancelResponse{Disposition: latent.CancelNotFound}, nil
	}
	if f.status.TerminalState != nil {
		return latent.CancelResponse{
			Disposition: latent.CancelAlreadyTerminal, TerminalState: f.status.TerminalState,
		}, nil
	}
	f.cancellationRequested = true
	return latent.CancelResponse{Disposition: latent.CancelAccepted}, nil
}

func (f *fixtureClient) GetActivation(_ context.Context, activationID string) (latent.ActivationStatus, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.status == nil || f.status.ActivationID != activationID {
		return latent.ActivationStatus{}, errors.New("activation not found")
	}
	return *f.status, nil
}

func (f *fixtureClient) finish(t *testing.T, terminal string, loseResponse bool) {
	t.Helper()
	f.mu.Lock()
	id := f.status.ActivationID
	consumption := latent.BudgetConsumption{CPUFuel: 7}
	var outcome latent.InvocationOutcome
	switch terminal {
	case "completed":
		f.status.Phase = "committed"
		f.status.TerminalOutcome = &latent.RetainedInvocationOutcome{
			Succeeded: &latent.ActivationSuccessSummary{},
		}
		outcome.Success = &latent.InvokeResponse{
			ActivationID: id, RevisionID: "fixture-revision", ReleaseDigest: "fixture-release",
			RouteGeneration: 1, Payload: []byte("finished"), MediaType: "text/plain", Consumption: consumption,
		}
	case "cancelled":
		failure := latent.PlatformError{Code: "cancelled", Message: "fixture cancellation acknowledged"}
		f.status.TerminalOutcome = &latent.RetainedInvocationOutcome{PlatformFailure: &failure}
		outcome.PlatformFailure = &latent.PlatformInvocationFailure{
			Receipt: latent.InvocationReceipt{
				ActivationID: id, RevisionID: "fixture-revision", ReleaseDigest: "fixture-release",
				RouteGeneration: 1, Consumption: consumption,
			},
			Error: failure,
		}
	default:
		f.mu.Unlock()
		t.Fatalf("unsupported fixture terminal state %q", terminal)
	}
	f.status.TerminalState = stringPointer(terminal)
	f.status.FinalConsumption = &consumption
	f.status.LastUpdatedUnixMS = 2
	terminalAt := uint64(2)
	f.status.TerminalAtUnixMS = &terminalAt
	f.mu.Unlock()
	result := invokeResult{outcome: outcome}
	if loseResponse {
		result = invokeResult{err: errors.New("invocation response lost")}
	}
	f.response <- result
}

func start(t *testing.T, f *fixtureClient, request latent.InvokeRequest) (<-chan invokeResult, context.CancelFunc) {
	t.Helper()
	ctx, cancel := context.WithCancel(context.Background())
	t.Cleanup(cancel)
	done := make(chan invokeResult, 1)
	var client latent.Client = f
	go func() {
		outcome, err := client.Invoke(ctx, request)
		done <- invokeResult{outcome, err}
	}()
	<-f.started
	assertPending(t, done)
	return done, cancel
}

func assertPending(t *testing.T, done <-chan invokeResult) {
	t.Helper()
	select {
	case result := <-done:
		t.Fatalf("invocation completed before fixture server finished: %+v", result)
	default:
	}
}

func getStatus(t *testing.T, client latent.Client, id string) latent.ActivationStatus {
	t.Helper()
	status, err := client.GetActivation(context.Background(), id)
	if err != nil {
		t.Fatal(err)
	}
	if status.ActivationID != id {
		t.Fatalf("status identified %q instead of %q", status.ActivationID, id)
	}
	return status
}

func assertCancel(t *testing.T, client latent.Client, id string, disposition latent.CancelDisposition, terminal *string) {
	t.Helper()
	response, err := client.Cancel(context.Background(), id, "stop")
	if err != nil {
		t.Fatal(err)
	}
	if response.Disposition != disposition {
		t.Fatalf("cancel disposition = %q, want %q", response.Disposition, disposition)
	}
	if terminal == nil {
		if response.TerminalState != nil {
			t.Fatalf("nonterminal disposition carried terminal state %q", *response.TerminalState)
		}
	} else if response.TerminalState == nil || *response.TerminalState != *terminal {
		t.Fatalf("cancel terminal state = %v, want %q", response.TerminalState, *terminal)
	}
}
