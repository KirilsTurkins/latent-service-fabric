package providerworkflow

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"time"

	"latent.dev/sdk/go/profile"
)

type invocationResult struct {
	response profile.ClientResponse[profile.InvokeResponse]
	failure  error
}

func (owner *workflow) heldCases(ctx context.Context) error {
	for _, kind := range []string{"local-cancel", "explicit-cancel", "deadline", "shutdown"} {
		if failure := owner.held(ctx, kind); failure != nil {
			return failure
		}
	}
	return nil
}

func (owner *workflow) held(parent context.Context, kind string) (outcome error) {
	identity := "go-" + kind
	mode := "hold-" + identity
	if failure := owner.mode(mode); failure != nil {
		return failure
	}
	defer owner.mode("reply")
	client := owner.client
	if kind == "shutdown" {
		var failure error
		client, failure = owner.open(parent, owner.config)
		if failure != nil {
			return errors.New("participant-shutdown-client-connect-failed")
		}
	}
	ctx, cancel := context.WithCancel(parent)
	request := owner.request("http", identity)
	options := profile.CallOptions{}
	started := time.Now()
	if kind == "deadline" {
		request.DeadlineUnixMillis = reference(uint64(time.Now().Add(500 * time.Millisecond).UnixMilli()))
		options.TimeoutMillis = reference(uint64(500))
	}
	result := make(chan invocationResult, 1)
	retired := make(chan struct{})
	go func() {
		defer close(retired)
		response, failure := client.Invoke(ctx, request, options)
		result <- invocationResult{response: response, failure: failure}
	}()
	defer func() {
		cancel()
		timer := time.NewTimer(2500 * time.Millisecond)
		defer timer.Stop()
		select {
		case <-retired:
		case <-timer.C:
			outcome = errors.New("participant-invocation-owner-did-not-retire")
		}
	}()
	if failure := owner.marker(parent, "started-"+mode); failure != nil {
		cancel()
		_, _ = awaitInvocation(parent, result)
		return failure
	}
	status, failure := owner.client.GetActivation(parent, profile.GetActivationRequest{ActivationId: identity}, profile.CallOptions{TimeoutMillis: reference(uint64(1000))})
	if failure != nil || status.Value.TerminalState != nil {
		return errors.New("participant-started-activation-not-pending")
	}
	owner.observe(status.Metadata)
	switch kind {
	case "local-cancel":
		cancel()
	case "explicit-cancel":
		if failure := owner.cancel(parent, identity); failure != nil {
			return failure
		}
	case "shutdown":
		if client.Close() != nil || !client.Snapshot().Reaped {
			return errors.New("participant-shutdown-with-outstanding-work-failed")
		}
	}
	completed, failure := awaitInvocation(parent, result)
	if failure != nil {
		return failure
	}
	owner.observe(completed.response.Metadata)
	owner.observeFailure(completed.failure)
	var detail *profile.ClientFailure
	switch kind {
	case "local-cancel":
		if !errors.Is(completed.failure, context.Canceled) || !errors.As(completed.failure, &detail) || !detail.Dispatched ||
			detail.Identity.ActivationId == nil || *detail.Identity.ActivationId != identity || detail.Outcome != profile.OutcomeKnowledgeUnknown {
			return errors.New("participant-local-cancellation-lost-identity-or-uncertainty")
		}
		owner.result.Assertions["localCancellation"] = true
	case "deadline":
		deadlineFailure := errors.Is(completed.failure, context.DeadlineExceeded) ||
			(completed.response.Value.PlatformFailure != nil && completed.response.Value.PlatformFailure.Code == "deadline-exceeded")
		if !deadlineFailure || time.Since(started) > 2500*time.Millisecond {
			return errors.New("participant-original-absolute-deadline-not-observed")
		}
		owner.result.Assertions["absoluteDeadline"] = true
	case "shutdown":
		if !errors.As(completed.failure, &detail) || detail.Category != profile.FailureCategoryTransport || !detail.Dispatched || detail.Outcome != profile.OutcomeKnowledgeUnknown {
			return errors.New("participant-close-invented-remote-outcome")
		}
		owner.result.Assertions["shutdownOutstanding"] = true
	case "explicit-cancel":
		owner.result.Assertions["explicitCancellation"] = true
	}
	status, failure = owner.client.GetActivation(parent, profile.GetActivationRequest{ActivationId: identity}, profile.CallOptions{TimeoutMillis: reference(uint64(1000))})
	if failure != nil {
		return errors.New("participant-original-id-status-after-lost-response-failed")
	}
	owner.observe(status.Metadata)
	if status.Value.TerminalState == nil {
		if failure := owner.cancel(parent, identity); failure != nil {
			return failure
		}
	}
	if failure := owner.marker(parent, "closed-"+mode); failure != nil {
		return failure
	}
	if failure := owner.retain(parent, identity); failure != nil {
		return failure
	}
	if kind == "local-cancel" {
		owner.result.Assertions["lostResponseStatus"] = true
	}
	return nil
}

func awaitInvocation(parent context.Context, result <-chan invocationResult) (invocationResult, error) {
	timer := time.NewTimer(2500 * time.Millisecond)
	defer timer.Stop()
	select {
	case value := <-result:
		return value, nil
	case <-parent.Done():
		return invocationResult{}, errors.New("participant-workflow-deadline")
	case <-timer.C:
		return invocationResult{}, errors.New("participant-invocation-did-not-retire")
	}
}

func (owner *workflow) cancel(ctx context.Context, identity string) error {
	response, failure := owner.client.Cancel(ctx, profile.CancelRequest{ActivationId: identity, Reason: "explicit SDK fixture cleanup"}, profile.CallOptions{TimeoutMillis: reference(uint64(1000))})
	if failure != nil || (response.Value.Disposition != profile.CancelDispositionAccepted && response.Value.Disposition != profile.CancelDispositionAlreadyTerminal) {
		return errors.New("participant-explicit-cancellation-not-retained")
	}
	owner.observe(response.Metadata)
	return nil
}

func (owner *workflow) retain(parent context.Context, identity string) error {
	ctx, cancel := context.WithTimeout(parent, 2*time.Second)
	defer cancel()
	ticker := time.NewTicker(20 * time.Millisecond)
	defer ticker.Stop()
	for attempt := 0; attempt < 64; attempt++ {
		response, failure := owner.client.GetActivation(ctx, profile.GetActivationRequest{ActivationId: identity}, profile.CallOptions{TimeoutMillis: reference(uint64(1000))})
		if failure != nil {
			return errors.New("participant-admitted-activation-not-retained")
		}
		owner.observe(response.Metadata)
		if response.Value.TerminalState != nil && response.Value.FinalConsumption != nil && response.Value.TerminalAtUnixMillis != nil {
			owner.result.ActivationIDs = append(owner.result.ActivationIDs, identity)
			return nil
		}
		select {
		case <-ctx.Done():
			return errors.New("participant-retained-activation-not-terminal")
		case <-ticker.C:
		}
	}
	return errors.New("participant-status-poll-bound-exceeded")
}

func (owner *workflow) mode(value string) error {
	file, failure := os.CreateTemp(owner.input.ControlDirectory, "go-mode-")
	if failure != nil {
		return errors.New("participant-private-rendezvous-write-failed")
	}
	path := file.Name()
	defer os.Remove(path)
	if _, failure = file.WriteString(value); failure != nil {
		_ = file.Close()
		return errors.New("participant-private-rendezvous-write-failed")
	}
	if file.Close() != nil || os.Rename(path, filepath.Join(owner.input.ControlDirectory, "mode")) != nil {
		return errors.New("participant-private-rendezvous-publish-failed")
	}
	return nil
}

func (owner *workflow) marker(parent context.Context, name string) error {
	ctx, cancel := context.WithTimeout(parent, 2500*time.Millisecond)
	defer cancel()
	ticker := time.NewTicker(5 * time.Millisecond)
	defer ticker.Stop()
	for {
		info, failure := os.Lstat(filepath.Join(owner.input.ControlDirectory, name))
		if failure == nil {
			if !info.Mode().IsRegular() || info.Size() > 64 {
				return errors.New("participant-invalid-private-rendezvous")
			}
			return nil
		}
		if !errors.Is(failure, os.ErrNotExist) {
			return errors.New("participant-private-rendezvous-read-failed")
		}
		select {
		case <-ctx.Done():
			return errors.New("participant-private-rendezvous-timeout")
		case <-ticker.C:
		}
	}
}
