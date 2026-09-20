package providerworkflow

import (
	"errors"
	"latent.dev/sdk/go/profile"
	"regexp"
	"strings"
)

// FailureRecord contains only fixed workflow labels and numeric protocol codes.
// Peer messages, error details, credentials and payloads are never projected.
type FailureRecord struct {
	Stage      string                   `json:"stage"`
	Reason     string                   `json:"reason"`
	Category   *profile.FailureCategory `json:"category,omitempty"`
	GrpcStatus *int32                   `json:"grpcStatus,omitempty"`
}

type stepFailure struct {
	reason string
	cause  error
}

func (failure *stepFailure) Error() string { return failure.reason }
func (failure *stepFailure) Unwrap() error { return failure.cause }

func FailureDiagnostic(failure error) FailureRecord {
	reason := strings.ToLower(failure.Error())
	if valid, _ := regexp.MatchString(`^participant-[a-z0-9-]{1,68}$`, reason); !valid {
		reason = "participant-failed"
	}
	record := FailureRecord{Stage: "go-participant", Reason: reason}
	var detail *profile.ClientFailure
	if errors.As(failure, &detail) {
		record.Category = &detail.Category
		record.GrpcStatus = detail.GrpcStatus
	}
	return record
}
