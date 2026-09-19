package profile

import (
	"context"
	"errors"
	"sync"
	"testing"
	"time"
)

type fixtureProfile struct {
	mutex   sync.Mutex
	writes  int
	pages   int
	cancels int
	waiters int
	started chan struct{}
	receipt *CapabilityPolicyOperation
	policy  *Policy
}

var _ ClientProfile = (*fixtureProfile)(nil)

func fixtureResponse[Response any](value Response) ClientResponse[Response] {
	return ClientResponse[Response]{Value: value, Metadata: ResponseMetadata{Outcome: OutcomeKnowledgeObserved}}
}

func (client *fixtureProfile) Invoke(_ context.Context, request InvokeRequest, _ CallOptions) (ClientResponse[InvokeResponse], error) {
	return fixtureResponse(InvokeResponse{ActivationId: *request.ActivationId, Success: &Success{Payload: append([]byte(nil), request.Payload...)}}), nil
}

func (client *fixtureProfile) Cancel(_ context.Context, _ CancelRequest, _ CallOptions) (ClientResponse[CancelResponse], error) {
	client.mutex.Lock()
	defer client.mutex.Unlock()
	client.cancels++
	return fixtureResponse(CancelResponse{Disposition: CancelDispositionAccepted}), nil
}

func (client *fixtureProfile) GetActivation(_ context.Context, request GetActivationRequest, _ CallOptions) (ClientResponse[ActivationStatus], error) {
	return fixtureResponse(ActivationStatus{ActivationId: request.ActivationId, Phase: "running"}), nil
}

func (client *fixtureProfile) GetPolicy(_ context.Context, _ GetPolicyRequest, _ CallOptions) (ClientResponse[GetPolicyResponse], error) {
	client.mutex.Lock()
	defer client.mutex.Unlock()
	return fixtureResponse(GetPolicyResponse{Policy: client.policy}), nil
}

func (client *fixtureProfile) ListPolicies(_ context.Context, _ ListPoliciesRequest, _ CallOptions) (ClientResponse[ListPoliciesResponse], error) {
	client.mutex.Lock()
	defer client.mutex.Unlock()
	client.pages++
	return fixtureResponse(ListPoliciesResponse{Page: &PageResponse{NextPageToken: fixturePointer("opaque-next-page")}}), nil
}

func (client *fixtureProfile) ListCapabilities(_ context.Context, request ListCapabilitiesRequest, _ CallOptions) (ClientResponse[ListCapabilitiesResponse], error) {
	return fixtureResponse(ListCapabilitiesResponse{Revision: &CapabilityInspectionRevision{DeploymentId: request.DeploymentId}}), nil
}

func (client *fixtureProfile) ApplyPolicy(ctx context.Context, request ApplyPolicyRequest, options CallOptions) (ClientResponse[ApplyPolicyResponse], error) {
	identity := RequestIdentity{OperationId: fixturePointer(request.OperationId)}
	if ctx.Err() != nil || (options.TimeoutMillis != nil && *options.TimeoutMillis == 0) {
		category := FailureCategoryDeadline
		if errors.Is(ctx.Err(), context.Canceled) {
			category = FailureCategoryLocalCancelled
		}
		return ClientResponse[ApplyPolicyResponse]{}, &ClientFailure{Category: category, Identity: identity, Outcome: OutcomeKnowledgeNotDispatched}
	}
	if request.ExpectedGeneration == nil || request.OperationId == "" || request.Policy == nil {
		return ClientResponse[ApplyPolicyResponse]{}, &ClientFailure{Category: FailureCategoryInvalidRequest, Identity: identity, Outcome: OutcomeKnowledgeNotDispatched}
	}
	client.mutex.Lock()
	if client.receipt != nil {
		receipt := *client.receipt
		client.mutex.Unlock()
		return fixtureResponse(ApplyPolicyResponse{Receipt: &receipt}), nil
	}
	client.receipt = &CapabilityPolicyOperation{OperationId: request.OperationId, Tenant: "tenant-a", Id: request.Policy.Id, RecordKind: request.Policy.RecordKind, Generation: ^uint64(0)}
	copied := *request.Policy
	client.policy = &copied
	client.writes++
	client.waiters++
	client.mutex.Unlock()
	defer func() { client.mutex.Lock(); client.waiters--; client.mutex.Unlock() }()
	client.started <- struct{}{}
	<-ctx.Done()
	return ClientResponse[ApplyPolicyResponse]{}, &ClientFailure{Category: FailureCategoryLocalCancelled, Message: "local-cancelled", Dispatched: true, Outcome: OutcomeKnowledgeUnknown, Identity: identity}
}

func (client *fixtureProfile) GetPolicyOperation(_ context.Context, request GetPolicyOperationRequest, _ CallOptions) (ClientResponse[GetPolicyOperationResponse], error) {
	client.mutex.Lock()
	defer client.mutex.Unlock()
	response := fixtureResponse(GetPolicyOperationResponse{})
	response.Metadata.Identity.OperationId = fixturePointer(request.OperationId)
	response.Metadata.Outcome = OutcomeKnowledgeUnknown
	if client.receipt != nil && client.receipt.OperationId == request.OperationId {
		receipt := *client.receipt
		response.Value.Receipt = &receipt
		response.Metadata.Outcome = OutcomeKnowledgeObserved
	}
	return response, nil
}

func TestLocalCancellationRetainsRecoveryAndBoundedPages(tester *testing.T) {
	client := &fixtureProfile{started: make(chan struct{}, 1)}
	var profile ClientProfile = client
	request := ApplyPolicyRequest{OperationId: "operation-a", ExpectedGeneration: fixturePointer(uint64(0)), Policy: &Policy{Id: "policy-a", RecordKind: CapabilityPolicyRecordKindPolicy}}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	completed := make(chan error, 1)
	go func() { _, failure := profile.ApplyPolicy(ctx, request, CallOptions{}); completed <- failure }()
	select {
	case <-client.started:
	case <-time.After(2 * time.Second):
		tester.Fatal("fixture did not dispatch")
	}
	cancel()
	var failure error
	select {
	case failure = <-completed:
	case <-time.After(2 * time.Second):
		tester.Fatal("local cancellation did not complete")
	}
	var typed *ClientFailure
	if !errors.As(failure, &typed) || !errors.Is(failure, context.Canceled) || !typed.Dispatched || typed.Outcome != OutcomeKnowledgeUnknown || *typed.Identity.OperationId != "operation-a" {
		tester.Fatal("local cancellation lost typed uncertainty or identity")
	}
	if client.writes != 1 || client.waiters != 0 || client.cancels != 0 {
		tester.Fatal("local cancellation changed server ownership")
	}
	recovered, failure := profile.GetPolicyOperation(context.Background(), GetPolicyOperationRequest{OperationId: "operation-a"}, CallOptions{})
	if failure != nil || recovered.Value.Receipt.Generation != ^uint64(0) || recovered.Metadata.AuditAck != nil {
		tester.Fatal("original receipt or audit presence lost")
	}
	unknown, _ := profile.GetPolicyOperation(context.Background(), GetPolicyOperationRequest{OperationId: "not-retained"}, CallOptions{})
	if unknown.Value.Receipt != nil || unknown.Metadata.Outcome != OutcomeKnowledgeUnknown {
		tester.Fatal("missing receipt is not nonexecution")
	}
	if _, failure := profile.ApplyPolicy(context.Background(), request, CallOptions{}); failure != nil || client.writes != 1 {
		tester.Fatal("explicit replay changed original outcome")
	}
	_, failure = profile.ApplyPolicy(context.Background(), request, CallOptions{TimeoutMillis: fixturePointer(uint64(0))})
	if !errors.As(failure, &typed) || typed.Dispatched || !errors.Is(failure, context.DeadlineExceeded) {
		tester.Fatal("zero timeout did not remain local")
	}
	payload := []byte{1, 2}
	invoked, _ := profile.Invoke(context.Background(), InvokeRequest{ActivationId: fixturePointer("activation-a"), Payload: payload}, CallOptions{})
	payload[0] = 99
	if invoked.Value.Success.Payload[0] != 1 {
		tester.Fatal("response aliases request memory")
	}
	cancelled, _ := profile.Cancel(context.Background(), CancelRequest{ActivationId: "activation-a"}, CallOptions{})
	status, _ := profile.GetActivation(context.Background(), GetActivationRequest{ActivationId: "activation-a"}, CallOptions{})
	if cancelled.Value.Disposition != CancelDispositionAccepted || status.Value.Phase != "running" {
		tester.Fatal("accepted implies no cleanup guarantee")
	}
	policy, _ := profile.GetPolicy(context.Background(), GetPolicyRequest{Id: "policy-a", RecordKind: CapabilityPolicyRecordKindPolicy}, CallOptions{})
	if policy.Value.Policy.Id != "policy-a" {
		tester.Fatal("policy identity lost")
	}
	page, _ := profile.ListPolicies(context.Background(), ListPoliciesRequest{RecordKind: CapabilityPolicyRecordKindPolicy, Page: &PageRequest{PageSize: 1}}, CallOptions{})
	if page.Value.Page.NextPageToken == nil || client.pages != 1 {
		tester.Fatal("listing must not auto-drain")
	}
	capabilities, _ := profile.ListCapabilities(context.Background(), ListCapabilitiesRequest{DeploymentId: "deployment-a"}, CallOptions{})
	if capabilities.Value.Revision.DeploymentId != "deployment-a" {
		tester.Fatal("deployment selection lost")
	}
}
