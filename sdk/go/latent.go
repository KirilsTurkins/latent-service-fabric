// Package latent defines the interface-only Go client surface for LSF.
package latent

import "context"

type ResourceBudget struct {
	CPUFuel     uint64
	MemoryBytes uint64
	// Relative to admission. Nil adds no ceiling; a pointer to zero grants no
	// wall time. It is never an absolute Unix timestamp.
	WallTimeLimitMillis *uint64
	ChildCalls          uint32
	OutboundRequests    uint32
	StateReadBytes      uint64
	StateWriteBytes     uint64
	BlobReadBytes       uint64
	BlobWriteBytes      uint64
	LogBytes            uint64
	EffectCount         uint32
}

type BudgetConsumption struct {
	CPUFuel          uint64
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

type Target struct {
	Tenant   string
	Service  string
	Contract string
	Function string
	Route    *string
}

type InvokeOptions struct {
	DeadlineUnixMillis *uint64
	Priority           uint8
	IdempotencyKey     *string
	Budget             ResourceBudget
	Metadata           map[string]string
}

type InvokeRequest struct {
	Target    Target
	Payload   []byte
	MediaType string
	Options   InvokeOptions
}

type InvokeResponse struct {
	ActivationID          string
	RevisionID            string
	ReleaseDigest         string
	RouteGeneration       uint64
	Payload               []byte
	MediaType             string
	CommittedStateVersion *string
	EffectIDs             []string
	Consumption           BudgetConsumption
	Metadata              map[string]string
}

type PlatformError struct {
	Code      string
	Message   string
	Retryable bool
	Details   []ErrorDetail
}

func (e *PlatformError) Error() string { return e.Message }

type ErrorDetail struct {
	Kind   string
	Fields map[string]string
}

type DeclaredError struct {
	Code      string
	Message   string
	Payload   []byte
	MediaType string
	Metadata  map[string]string
}

type InvocationReceipt struct {
	ActivationID    string
	RevisionID      string
	ReleaseDigest   string
	RouteGeneration uint64
	Consumption     BudgetConsumption
}

type DeclaredInvocationError struct {
	Receipt InvocationReceipt
	Error   DeclaredError
}

type PlatformInvocationFailure struct {
	Receipt InvocationReceipt
	Error   PlatformError
}

// Exactly one pointer is populated for a successful RPC response.
type InvocationOutcome struct {
	Success         *InvokeResponse
	DeclaredError   *DeclaredInvocationError
	PlatformFailure *PlatformInvocationFailure
}

type CancelDisposition string

const (
	CancelAccepted        CancelDisposition = "accepted"
	CancelAlreadyTerminal CancelDisposition = "already-terminal"
	CancelNotFound        CancelDisposition = "not-found"
)

type CancelResponse struct {
	Disposition   CancelDisposition
	TerminalState *string
}

type RetainedInvocationOutcome struct {
	Succeeded       *ActivationSuccessSummary
	DeclaredError   *DeclaredError
	PlatformFailure *PlatformError
}

type ActivationSuccessSummary struct {
	CommittedStateVersion *string
	EffectIDs             []string
	Metadata              map[string]string
}

type ActivationStatus struct {
	ActivationID      string
	Phase             string
	TerminalState     *string
	TerminalOutcome   *RetainedInvocationOutcome
	FinalConsumption  *BudgetConsumption
	LastUpdatedUnixMS uint64
	TerminalAtUnixMS  *uint64
	Metadata          map[string]string
}

type Client interface {
	// error represents transport/authentication/decoding failure. Platform and
	// declared component failures are explicit InvocationOutcome values.
	Invoke(ctx context.Context, request InvokeRequest) (InvocationOutcome, error)
	Cancel(ctx context.Context, activationID string, reason string) (CancelResponse, error)
	GetActivation(ctx context.Context, activationID string) (ActivationStatus, error)
}

type GuestContext interface {
	ActivationID() string
	RootActivationID() string
	ParentActivationID() *string
	DeadlineUnixMillis() *uint64
	RemainingBudget() ResourceBudget
	Metadata() map[string]string
}
