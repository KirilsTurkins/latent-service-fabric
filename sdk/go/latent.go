// Package latent defines the interface-only Go client surface for LSF.
package latent

import "context"

type ResourceBudget struct {
	CPUFuel                uint64
	MemoryBytes            uint64
	WallDeadlineUnixMillis *uint64
	ChildCalls             uint32
	OutboundRequests       uint32
	StateReadBytes         uint64
	StateWriteBytes        uint64
	BlobReadBytes          uint64
	BlobWriteBytes         uint64
	LogBytes               uint64
	EffectCount            uint32
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
	Details   map[string]string
}

func (e *PlatformError) Error() string { return e.Message }

type Client interface {
	Invoke(ctx context.Context, request InvokeRequest) (InvokeResponse, error)
	Cancel(ctx context.Context, activationID string, reason string) error
}

type GuestContext interface {
	ActivationID() string
	RootActivationID() string
	ParentActivationID() *string
	DeadlineUnixMillis() *uint64
	RemainingBudget() ResourceBudget
	Metadata() map[string]string
}
