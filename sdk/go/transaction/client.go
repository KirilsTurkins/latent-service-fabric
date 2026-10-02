// Package transaction defines owned caller-scoped command/query/recovery models.
package transaction

import (
	"context"
	"latent.dev/sdk/go/profile"
)

// RecoveryIdentity preserves the original admission and explicit-recovery values.
// None of these values is a transferable grant or proof of authority.
type RecoveryIdentity struct {
	Namespace                    *NamespaceSelector
	Command                      *CommandSelector
	ActivationId                 *string
	OperationId                  *string
	CommandId                    *string
	AttemptId                    *string
	ReceiptId                    *string
	EffectId                     *string
	RetryRequestId               *string
	ExpectedAbort                *AbortFence
	ExpectedVersions             []ExpectedVersion
	ExpectedGeneration           *uint64
	ExpectedVersion              *[]byte
	ExpectedPolicyDigest         *string
	FingerprintSha256            []byte
	AuthorizationPublication     *profile.PublicationRef
	DispatcherAction             *DispatcherAction
	DispatcherExpectedGeneration *DispatcherGeneration
	EffectMutation               *PlanEffectMutationRequest
	EffectPlan                   *EffectManagementPlan
}

// ObservedOutcome retains bounded validated receipts independently of application bytes.
type ObservedOutcome struct {
	Command    *CommandInspection
	State      *StateOperationReceipt
	Namespace  *NamespaceOperationReceipt
	Effect     *EffectReceipt
	Dispatcher *DispatcherOperationReceipt
	EffectPlan *EffectManagementPlan
}

// ResponseMetadata keeps transport/audit knowledge separate from a durable observation.
type ResponseMetadata struct {
	Transport profile.ResponseMetadata
	Identity  RecoveryIdentity
	Observed  *ObservedOutcome
}

// ClientResponse owns its response and bounded recovery metadata.
type ClientResponse[Response any] struct {
	Value    Response
	Metadata ResponseMetadata
}

// ClientFailure preserves the original identity and any observed durable receipt.
type ClientFailure struct {
	Transport *profile.ClientFailure
	Identity  RecoveryIdentity
	Observed  *ObservedOutcome
}

func (failure *ClientFailure) Error() string { return failure.Transport.Error() }

// Unwrap preserves errors.As for the maintained profile and native cancellation classification.
func (failure *ClientFailure) Unwrap() error {
	return failure.Transport
}
func (*ClientFailure) String() string   { return "latent transaction client failure (redacted)" }
func (*ClientFailure) GoString() string { return "transaction.ClientFailure{redacted}" }

// Client is implemented by the maintained bounded HTTP/2 transport.
// Calls never automatically retry mutations, refresh preconditions, or drain pages.
type Client interface {
	InvokeCommand(context.Context, InvokeCommandRequest, profile.CallOptions) (ClientResponse[InvokeCommandResponse], error)
	Query(context.Context, QueryRequest, profile.CallOptions) (ClientResponse[QueryResponse], error)
	LookupCommand(context.Context, LookupCommandRequest, profile.CallOptions) (ClientResponse[LookupCommandResponse], error)
	LookupCommit(context.Context, LookupCommitRequest, profile.CallOptions) (ClientResponse[LookupCommitResponse], error)
	GetEffect(context.Context, GetEffectRequest, profile.CallOptions) (ClientResponse[GetEffectResponse], error)
	ListEffectHistory(context.Context, ListEffectHistoryRequest, profile.CallOptions) (ClientResponse[ListEffectHistoryResponse], error)
	CancelCommand(context.Context, CancelCommandRequest, profile.CallOptions) (ClientResponse[CancelCommandResponse], error)
	InspectNamespace(context.Context, InspectNamespaceRequest, profile.CallOptions) (ClientResponse[InspectNamespaceResponse], error)
	MutateNamespace(context.Context, MutateNamespaceRequest, profile.CallOptions) (ClientResponse[MutateNamespaceResponse], error)
	SelectEntity(context.Context, SelectEntityRequest, profile.CallOptions) (ClientResponse[SelectEntityResponse], error)
	MutateState(context.Context, MutateStateRequest, profile.CallOptions) (ClientResponse[MutateStateResponse], error)
	PlanEffectMutation(context.Context, PlanEffectMutationRequest, profile.CallOptions) (ClientResponse[PlanEffectMutationResponse], error)
	GetStateOperationReceipt(context.Context, GetStateOperationReceiptRequest, profile.CallOptions) (ClientResponse[GetStateOperationReceiptResponse], error)
	InspectDispatcher(context.Context, InspectDispatcherRequest, profile.CallOptions) (ClientResponse[InspectDispatcherResponse], error)
	ControlDispatcher(context.Context, ControlDispatcherRequest, profile.CallOptions) (ClientResponse[ControlDispatcherResponse], error)
	GetDispatcherOperation(context.Context, GetDispatcherOperationRequest, profile.CallOptions) (ClientResponse[GetDispatcherOperationResponse], error)
}
