package profile

import (
	"context"
	"strconv"
)

type AuditAckStatus int32

const (
	AuditAckStatusUnspecified      AuditAckStatus = 0
	AuditAckStatusDurable          AuditAckStatus = 1
	AuditAckStatusOutcomeUnknown   AuditAckStatus = 2
	AuditAckStatusAuditUnavailable AuditAckStatus = 3
	AuditAckStatusDisabled         AuditAckStatus = 4
)

type CancelDisposition int32

const (
	CancelDispositionUnspecified     CancelDisposition = 0
	CancelDispositionAccepted        CancelDisposition = 1
	CancelDispositionAlreadyTerminal CancelDisposition = 2
	CancelDispositionNotFound        CancelDisposition = 3
)

type CapabilityPolicyRecordKind int32

const (
	CapabilityPolicyRecordKindUnspecified     CapabilityPolicyRecordKind = 0
	CapabilityPolicyRecordKindPolicy          CapabilityPolicyRecordKind = 1
	CapabilityPolicyRecordKindProviderBinding CapabilityPolicyRecordKind = 2
)

type FailureCategory int32

const (
	FailureCategoryUnspecified    FailureCategory = 0
	FailureCategoryLocalCancelled FailureCategory = 1
	FailureCategoryDeadline       FailureCategory = 2
	FailureCategoryTransport      FailureCategory = 3
	FailureCategoryRpc            FailureCategory = 4
	FailureCategoryDecode         FailureCategory = 5
	FailureCategoryLimit          FailureCategory = 6
	FailureCategoryInvalidRequest FailureCategory = 7
)

type OutcomeKnowledge int32

const (
	OutcomeKnowledgeUnspecified   OutcomeKnowledge = 0
	OutcomeKnowledgeNotDispatched OutcomeKnowledge = 1
	OutcomeKnowledgeUnknown       OutcomeKnowledge = 2
	OutcomeKnowledgeObserved      OutcomeKnowledge = 3
)

type ResourceBudget struct {
	CpuFuel             uint64
	MemoryBytes         uint64
	ChildCalls          uint32
	OutboundRequests    uint32
	StateReadBytes      uint64
	StateWriteBytes     uint64
	BlobReadBytes       uint64
	BlobWriteBytes      uint64
	LogBytes            uint64
	EffectCount         uint32
	WallTimeLimitMillis *uint64
}

type ErrorDetail struct {
	Kind   string
	Fields map[string]string
}

type PlatformError struct {
	Code        string
	Message     string
	Retryable   bool
	DetailItems []ErrorDetail
}

type ObjectMetadata struct {
	Name        string
	Tenant      *string
	Namespace   *string
	Labels      map[string]string
	Annotations map[string]string
}

type PageRequest struct {
	PageSize  uint32
	PageToken *string
}

type PageResponse struct {
	NextPageToken *string
}

type AuditAck struct {
	Status          AuditAckStatus
	AttemptSequence *uint64
}

type InvocationTarget struct {
	Tenant   string
	Service  string
	Contract string
	Function string
	Route    *string
}

type InvokeRequest struct {
	ActivationId       *string
	ParentActivationId *string
	RootActivationId   *string
	Target             *InvocationTarget
	Payload            []byte
	MediaType          string
	DeadlineUnixMillis *uint64
	Priority           uint32
	IdempotencyKey     *string
	Budget             *ResourceBudget
	Metadata           map[string]string
}

type BudgetConsumption struct {
	CpuFuel          uint64
	PeakMemoryBytes  uint64
	WallTimeMicros   uint64
	ChildCalls       uint32
	OutboundRequests uint32
	StateReadBytes   uint64
	StateWriteBytes  uint64
	BlobReadBytes    uint64
	BlobWriteBytes   uint64
	LogBytes         uint64
	EffectCount      uint32
}

type Success struct {
	Payload               []byte
	MediaType             string
	CommittedStateVersion *string
	EffectIds             []string
	Metadata              map[string]string
}

type DeclaredError struct {
	Code      string
	Message   string
	Payload   []byte
	MediaType string
	Metadata  map[string]string
}

type InvokeResponse struct {
	ActivationId    string
	RevisionId      string
	ReleaseDigest   string
	RouteGeneration uint64
	Success         *Success
	DeclaredError   *DeclaredError
	PlatformFailure *PlatformError
	Consumption     *BudgetConsumption
	PublicationId   *string
}

type CancelRequest struct {
	ActivationId string
	Reason       string
}

type CancelResponse struct {
	Disposition   CancelDisposition
	TerminalState *string
}

type GetActivationRequest struct {
	ActivationId string
}

type ActivationSuccessSummary struct {
	CommittedStateVersion *string
	EffectIds             []string
	Metadata              map[string]string
}

type ActivationStatus struct {
	ActivationId          string
	Phase                 string
	TerminalState         *string
	LastUpdatedUnixMillis uint64
	Metadata              map[string]string
	Succeeded             *ActivationSuccessSummary
	DeclaredError         *DeclaredError
	PlatformFailure       *PlatformError
	FinalConsumption      *BudgetConsumption
	TerminalAtUnixMillis  *uint64
}

type Policy struct {
	Id            string
	Metadata      *ObjectMetadata
	Document      string
	Generation    uint64
	Language      string
	RecordKind    CapabilityPolicyRecordKind
	ContentDigest string
	Revoked       bool
}

type ApplyPolicyRequest struct {
	Policy             *Policy
	ExpectedGeneration *uint64
	OperationId        string
}

type CapabilityPolicyOperation struct {
	OperationId   string
	Tenant        string
	Id            string
	RecordKind    CapabilityPolicyRecordKind
	Generation    uint64
	ContentDigest string
	Revoked       bool
}

type ApplyPolicyResponse struct {
	Policy  *Policy
	Receipt *CapabilityPolicyOperation
}

type GetPolicyRequest struct {
	Id         string
	RecordKind CapabilityPolicyRecordKind
}

type GetPolicyResponse struct {
	Policy *Policy
}

type GetPolicyOperationRequest struct {
	OperationId string
}

type GetPolicyOperationResponse struct {
	Receipt *CapabilityPolicyOperation
}

type ListPoliciesRequest struct {
	RecordKind CapabilityPolicyRecordKind
	Page       *PageRequest
}

type ListPoliciesResponse struct {
	Policies          []Policy
	CatalogGeneration uint64
	Page              *PageResponse
}

type CapabilityInspectionPolicy struct {
	Id       string
	Revision uint64
	Digest   string
}

type CapabilityBindingInspection struct {
	DefinitionDigest            *string
	ProviderBinding             *CapabilityInspectionPolicy
	Policies                    []CapabilityInspectionPolicy
	ProviderProfile             string
	ProviderConfigurationDigest string
	ProviderConfigurationEpoch  uint64
	State                       string
}

type CapabilityDescriptor struct {
	Id         string
	Contract   string
	Provider   string
	Operations []string
	Attributes map[string]string
	Inspection *CapabilityBindingInspection
}

type ListCapabilitiesRequest struct {
	ContractPrefix   *string
	Provider         *string
	Page             *PageRequest
	DeploymentId     string
	IncludeNodeUsage bool
}

type CapabilityInspectionRevision struct {
	DeploymentId       string
	RevisionId         string
	ComponentDigest    string
	PublicationId      *string
	RouteGeneration    uint64
	CatalogTransaction uint64
}

type CapabilityResourceUsage struct {
	Scope       string
	Counters    map[string]uint64
	Unavailable []string
}

type ListCapabilitiesResponse struct {
	Capabilities []CapabilityDescriptor
	Page         *PageResponse
	Revision     *CapabilityInspectionRevision
	TenantUsage  *CapabilityResourceUsage
	NodeUsage    *CapabilityResourceUsage
	State        string
}

type CapabilityInspectionCeiling struct {
	Operations     uint32
	InputBytes     uint64
	OutputBytes    uint64
	WallTimeMillis uint64
}

type PublicationRef struct {
	Id     string
	Tenant string
}

type ReleaseSelector struct {
	ComponentDigest *string
	Publication     *PublicationRef
}

type PublicationIdentity struct {
	Publication     PublicationRef
	ComponentDigest string
	PackageDigest   string
}

type CallOptions struct {
	TimeoutMillis *uint64
}

type RequestIdentity struct {
	ActivationId *string
	OperationId  *string
}

type UnsupportedWireValue struct {
	Field string
	Value string
}

type ResponseMetadata struct {
	Identity    RequestIdentity
	Outcome     OutcomeKnowledge
	AuditAck    *AuditAck
	AuditStatus *string
}

type ClientFailure struct {
	Category             FailureCategory
	Message              string
	GrpcStatus           *int32
	PlatformError        *PlatformError
	Dispatched           bool
	Outcome              OutcomeKnowledge
	Identity             RequestIdentity
	AuditAck             *AuditAck
	AuditStatus          *string
	UnsupportedWireValue *UnsupportedWireValue
}

type ClientResponse[Response any] struct {
	Value    Response
	Metadata ResponseMetadata
}

type ClientProfile interface {
	Invoke(ctx context.Context, request InvokeRequest, options CallOptions) (ClientResponse[InvokeResponse], error)
	Cancel(ctx context.Context, request CancelRequest, options CallOptions) (ClientResponse[CancelResponse], error)
	GetActivation(ctx context.Context, request GetActivationRequest, options CallOptions) (ClientResponse[ActivationStatus], error)
	GetPolicy(ctx context.Context, request GetPolicyRequest, options CallOptions) (ClientResponse[GetPolicyResponse], error)
	ListPolicies(ctx context.Context, request ListPoliciesRequest, options CallOptions) (ClientResponse[ListPoliciesResponse], error)
	ListCapabilities(ctx context.Context, request ListCapabilitiesRequest, options CallOptions) (ClientResponse[ListCapabilitiesResponse], error)
	ApplyPolicy(ctx context.Context, request ApplyPolicyRequest, options CallOptions) (ClientResponse[ApplyPolicyResponse], error)
	GetPolicyOperation(ctx context.Context, request GetPolicyOperationRequest, options CallOptions) (ClientResponse[GetPolicyOperationResponse], error)
}

func (failure *ClientFailure) Error() string { return failure.Message }

func (failure *ClientFailure) Unwrap() error {
	switch failure.Category {
	case FailureCategoryLocalCancelled:
		return context.Canceled
	case FailureCategoryDeadline:
		return context.DeadlineExceeded
	default:
		return nil
	}
}

func ParseU64Decimal(value string) (uint64, bool) {
	parsed, failure := strconv.ParseUint(value, 10, 64)
	return parsed, failure == nil && strconv.FormatUint(parsed, 10) == value
}
