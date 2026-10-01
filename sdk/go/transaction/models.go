// Generated from the authoritative transaction client descriptors.
package transaction

import "latent.dev/sdk/go/profile"

type CommandCancelDisposition int32

const (
	CommandCancelDispositionUnspecified      CommandCancelDisposition = 0
	CommandCancelDispositionRequested        CommandCancelDisposition = 1
	CommandCancelDispositionAlreadyCommitted CommandCancelDisposition = 2
	CommandCancelDispositionAlreadyTerminal  CommandCancelDisposition = 3
	CommandCancelDispositionNotFound         CommandCancelDisposition = 4
	CommandCancelDispositionRecoveryRequired CommandCancelDisposition = 5
)

type CommandOutcome int32

const (
	CommandOutcomeUnspecified      CommandOutcome = 0
	CommandOutcomeInProgress       CommandOutcome = 1
	CommandOutcomeCommitted        CommandOutcome = 2
	CommandOutcomeRejected         CommandOutcome = 3
	CommandOutcomeAborted          CommandOutcome = 4
	CommandOutcomeUnknown          CommandOutcome = 5
	CommandOutcomeRecoveryRequired CommandOutcome = 6
	CommandOutcomeExpired          CommandOutcome = 7
)

type DispatcherAction int32

const (
	DispatcherActionUnspecified DispatcherAction = 0
	DispatcherActionPause       DispatcherAction = 1
	DispatcherActionResume      DispatcherAction = 2
)

type DispatcherFailure int32

const (
	DispatcherFailureUnspecified       DispatcherFailure = 0
	DispatcherFailureNone              DispatcherFailure = 1
	DispatcherFailureAuthority         DispatcherFailure = 2
	DispatcherFailureStore             DispatcherFailure = 3
	DispatcherFailureWorker            DispatcherFailure = 4
	DispatcherFailureRestoreCheckpoint DispatcherFailure = 5
	DispatcherFailureAdmissionClosed   DispatcherFailure = 6
	DispatcherFailureConfiguration     DispatcherFailure = 7
)

type DispatcherScope int32

const (
	DispatcherScopeUnspecified DispatcherScope = 0
	DispatcherScopeNode        DispatcherScope = 1
)

type EffectDisposition int32

const (
	EffectDispositionUnspecified                EffectDisposition = 0
	EffectDispositionPending                    EffectDisposition = 1
	EffectDispositionDispatching                EffectDisposition = 2
	EffectDispositionProviderAcknowledged       EffectDisposition = 3
	EffectDispositionKnownFailure               EffectDisposition = 4
	EffectDispositionUncertainAfterDispatch     EffectDisposition = 5
	EffectDispositionExpired                    EffectDisposition = 6
	EffectDispositionPolicyBlocked              EffectDisposition = 7
	EffectDispositionAdministrativelyTerminated EffectDisposition = 8
)

type NamespaceMutationKind int32

const (
	NamespaceMutationKindUnspecified NamespaceMutationKind = 0
	NamespaceMutationKindCreate      NamespaceMutationKind = 1
	NamespaceMutationKindQuiesce     NamespaceMutationKind = 2
	NamespaceMutationKindRetire      NamespaceMutationKind = 3
	NamespaceMutationKindDestroy     NamespaceMutationKind = 4
	NamespaceMutationKindRecreate    NamespaceMutationKind = 5
)

type NamespaceStatus int32

const (
	NamespaceStatusUnspecified NamespaceStatus = 0
	NamespaceStatusActive      NamespaceStatus = 1
	NamespaceStatusQuiescing   NamespaceStatus = 2
	NamespaceStatusRetired     NamespaceStatus = 3
	NamespaceStatusTombstone   NamespaceStatus = 4
)

type StateMutationKind int32

const (
	StateMutationKindUnspecified            StateMutationKind = 0
	StateMutationKindRetryKnownFailedEffect StateMutationKind = 1
	StateMutationKindTerminateEffect        StateMutationKind = 2
	StateMutationKindPurgeExpiredPayload    StateMutationKind = 3
	StateMutationKindCheckpointNamespace    StateMutationKind = 4
)

type StateOperationDisposition int32

const (
	StateOperationDispositionUnspecified      StateOperationDisposition = 0
	StateOperationDispositionCommitted        StateOperationDisposition = 1
	StateOperationDispositionConflict         StateOperationDisposition = 2
	StateOperationDispositionRejected         StateOperationDisposition = 3
	StateOperationDispositionUnknown          StateOperationDisposition = 4
	StateOperationDispositionRecoveryRequired StateOperationDisposition = 5
)

type AbortFence struct {
	CommandId     string
	AttemptId     string
	TransactionId string
	OwnerFence    []byte
}

type TransactionProfile struct {
	Profile                  string
	HostAbiDigest            string
	PreparationProfileDigest string
}

type NamespaceSelector struct {
	Tenant      string
	Namespace   string
	Incarnation string
}

type CommandSelector struct {
	Namespace           *NamespaceSelector
	Operation           string
	Entity              *string
	ClientKey           string
	SharedRecoveryScope *string
}

type LookupCommandRequest struct {
	Profile                  *TransactionProfile
	Command                  *CommandSelector
	AttemptId                *string
	AuthorizationPublication *profile.PublicationRef
}

type CancelCommandRequest struct {
	Command *LookupCommandRequest
	Reason  string
}

type CommandKey struct {
	Namespace     *NamespaceSelector
	RecoveryScope string
	Operation     string
	Entity        *string
	ClientKey     string
}

type SourceIdentity struct {
	PublicationId   string
	RevisionId      string
	ReleaseDigest   string
	RouteGeneration uint64
	ContractDigest  string
	StateSchema     string
	InputFormat     string
	ResultFormat    string
	ComponentDigest string
}

type CommitReceipt struct {
	CommandId             string
	AttemptId             string
	TransactionId         string
	CommittedVersion      []byte
	CommittedAtUnixMillis uint64
	EffectIds             []string
	ReceiptId             string
	Source                *SourceIdentity
}

type LinkedRetention struct {
	RecordFormat                string
	RecordVersion               uint32
	PayloadExpiresAtUnixMillis  *uint64
	IdentityExpiresAtUnixMillis *uint64
	RemainingRecoveryMillis     *uint64
	RequiredRecordIds           []string
	PayloadAvailable            bool
}

type CommandInspection struct {
	Key                       *CommandKey
	CommandId                 string
	AttemptId                 string
	FingerprintSha256         []byte
	Outcome                   CommandOutcome
	MetadataDurable           bool
	ApplicationStateCommitted bool
	Source                    *SourceIdentity
	Success                   *profile.Success
	BusinessRejection         *profile.DeclaredError
	TechnicalFailure          *profile.PlatformError
	Commit                    *CommitReceipt
	ProvenAbort               *AbortFence
	Retention                 *LinkedRetention
	CleanupFailure            *profile.PlatformError
}

type CancelCommandResponse struct {
	Disposition CommandCancelDisposition
	Command     *CommandInspection
}

type DispatcherGeneration struct {
	OwnerEpoch uint64
	Revision   uint64
}

type ControlDispatcherRequest struct {
	Profile            *TransactionProfile
	Scope              DispatcherScope
	OperationId        string
	Action             DispatcherAction
	ExpectedGeneration *DispatcherGeneration
}

type DispatcherOperationReceipt struct {
	OperationId           string
	ReceiptId             string
	Action                DispatcherAction
	AuthenticatedOperator string
	ActorTenant           string
	BeforeGeneration      *DispatcherGeneration
	AfterGeneration       *DispatcherGeneration
	ObservedAtUnixMillis  uint64
	ClockContinuityProven bool
	RestoreReviewRequired bool
	Disposition           StateOperationDisposition
}

type ControlDispatcherResponse struct {
	Receipt   *DispatcherOperationReceipt
	Replayed  bool
	Published bool
	Paused    bool
	AuditAck  *profile.AuditAck
}

type DispatcherSnapshot struct {
	Generation                 *DispatcherGeneration
	Paused                     bool
	PendingControl             bool
	RestoreReviewRequired      bool
	AdmissionClosed            bool
	Quarantined                bool
	Failure                    DispatcherFailure
	Queued                     uint64
	ActiveJobs                 uint64
	RetainedAttemptBytes       uint64
	LiveWorkers                uint64
	AcceptedEffects            uint64
	PhysicalOwners             uint64
	QuarantinedPhysicalOwners  uint64
	CommandOwners              uint64
	Claims                     uint64
	PendingEffects             uint64
	UncertainEffects           uint64
	BlockedEffects             uint64
	DeadLetterEffects          uint64
	CountsObservedAtUnixMillis uint64
	ClockContinuityProven      bool
}

type EffectReceipt struct {
	EffectId                     string
	CommandId                    string
	CommandAttemptId             string
	DispatchAttempt              uint32
	Disposition                  EffectDisposition
	ProviderReceipt              *string
	FailureCode                  *string
	OccurredAtUnixMillis         uint64
	Retention                    *LinkedRetention
	ManagementOperationReceiptId *string
	ProviderProfile              string
}

type EntityInspection struct {
	Entity  string
	Version []byte
}

type ExpectedVersion struct {
	Key     []byte
	Absent  *bool
	Version *[]byte
}

type GetDispatcherOperationRequest struct {
	Original *ControlDispatcherRequest
}

type GetDispatcherOperationResponse struct {
	Receipt  *DispatcherOperationReceipt
	AuditAck *profile.AuditAck
}

type GetEffectRequest struct {
	Profile                  *TransactionProfile
	Command                  *CommandSelector
	EffectId                 string
	AuthorizationPublication *profile.PublicationRef
}

type GetEffectResponse struct {
	Effect *EffectReceipt
}

type InspectNamespaceRequest struct {
	Profile                  *TransactionProfile
	Namespace                *NamespaceSelector
	AuthorizationPublication *profile.PublicationRef
}

type GetStateOperationReceiptRequest struct {
	Namespace   *InspectNamespaceRequest
	OperationId string
}

type StateOperationReceipt struct {
	OperationId           string
	ReceiptId             string
	Mutation              StateMutationKind
	Namespace             *NamespaceSelector
	AuthenticatedOperator string
	BeforeVersion         []byte
	AfterVersion          []byte
	CompletedAtUnixMillis uint64
	RecordId              *string
	PolicyDigest          string
	Disposition           StateOperationDisposition
}

type NamespaceOperationReceipt struct {
	OperationId           string
	ReceiptId             string
	Mutation              NamespaceMutationKind
	Namespace             *NamespaceSelector
	AuthenticatedOperator string
	BeforeGeneration      *uint64
	AfterGeneration       uint64
	Status                NamespaceStatus
	StateSchema           string
	Disposition           StateOperationDisposition
}

type GetStateOperationReceiptResponse struct {
	Receipt          *StateOperationReceipt
	NamespaceReceipt *NamespaceOperationReceipt
}

type InspectDispatcherRequest struct {
	Profile *TransactionProfile
	Scope   DispatcherScope
}

type InspectDispatcherResponse struct {
	Dispatcher *DispatcherSnapshot
	AuditAck   *profile.AuditAck
}

type ViewIdentity struct {
	Namespace   *NamespaceSelector
	Version     []byte
	StateSchema string
}

type NamespaceQuota struct {
	StateKeys     uint64
	StateBytes    uint64
	ResultRows    uint64
	ResultBytes   uint64
	EffectRows    uint64
	EffectBytes   uint64
	PayloadBytes  uint64
	RecoveryBytes uint64
}

type NamespaceInspection struct {
	View                *ViewIdentity
	EncodedStateBytes   uint64
	CommandCount        uint64
	PendingEffectCount  uint64
	RetainedFormats     []LinkedRetention
	EngineProfile       string
	EngineProfileDigest string
	Status              NamespaceStatus
	Quota               *NamespaceQuota
	Generation          uint64
}

type InspectNamespaceResponse struct {
	Namespace *NamespaceInspection
}

type RetryAttempt struct {
	RequestId     string
	ExpectedAbort *AbortFence
}

type InvokeCommandRequest struct {
	Profile          *TransactionProfile
	Invocation       *profile.InvokeRequest
	Command          *CommandSelector
	InputFormat      string
	ExpectedVersions []ExpectedVersion
	RetryAttempt     *RetryAttempt
}

type InvokeCommandResponse struct {
	Invocation *profile.InvokeResponse
	Command    *CommandInspection
	Replayed   bool
}

type PageRequest struct {
	Limit  uint32
	Cursor *[]byte
}

type ListEffectHistoryRequest struct {
	Effect *GetEffectRequest
	Page   *PageRequest
}

type PageResponse struct {
	NextCursor    *[]byte
	ReturnedCount uint32
	EncodedBytes  uint64
}

type ListEffectHistoryResponse struct {
	Receipts []EffectReceipt
	Page     *PageResponse
}

type LookupCommandResponse struct {
	Command *CommandInspection
}

type LookupCommitRequest struct {
	Profile                  *TransactionProfile
	Command                  *CommandSelector
	ReceiptId                string
	AuthorizationPublication *profile.PublicationRef
}

type LookupCommitResponse struct {
	Command *CommandInspection
}

type NamespaceConfiguration struct {
	StateSchema string
	Quota       *NamespaceQuota
}

type MutateNamespaceRequest struct {
	Namespace          *InspectNamespaceRequest
	OperationId        string
	Mutation           NamespaceMutationKind
	ExpectedGeneration *uint64
	Configuration      *NamespaceConfiguration
}

type MutateNamespaceResponse struct {
	Receipt  *NamespaceOperationReceipt
	Replayed bool
	AuditAck *profile.AuditAck
}

type MutateStateRequest struct {
	Namespace            *InspectNamespaceRequest
	OperationId          string
	Mutation             StateMutationKind
	RecordId             *string
	ExpectedVersion      []byte
	ExpectedPolicyDigest string
	Reason               string
}

type MutateStateResponse struct {
	Receipt  *StateOperationReceipt
	AuditAck *profile.AuditAck
}

type QueryRequest struct {
	Profile            *TransactionProfile
	Invocation         *profile.InvokeRequest
	Namespace          *NamespaceSelector
	Entity             *string
	MinimumViewVersion *[]byte
}

type QueryResponse struct {
	Invocation           *profile.InvokeResponse
	View                 *ViewIdentity
	Source               *SourceIdentity
	ObservedAtUnixMillis uint64
}

type SelectEntityRequest struct {
	Namespace *InspectNamespaceRequest
	Prefix    *[]byte
	Page      *PageRequest
}

type SelectEntityResponse struct {
	Entities []EntityInspection
	Page     *PageResponse
}

// CurrentProfile describes the exact protocol; it grants no authority.
func CurrentProfile() TransactionProfile {
	return TransactionProfile{
		Profile:                  "lsf-transaction-v1",
		HostAbiDigest:            "sha256:3b85f790f85ab23d36e492d7bd4a04a1b8aab87fc6f67dd7d7498bcf28129d35",
		PreparationProfileDigest: "sha256:6acd7a248633dd01c9cdcbf8a1ed33fc5e6aa1d2edb09b7d89e53fda594b5507",
	}
}
