package providerworkflow

import (
	"encoding/json"
	"errors"
	"latent.dev/sdk/go/profile"
	"strings"
	"testing"
)

func TestFailureDiagnosticRetainsProtocolCodesWithoutPeerData(t *testing.T) {
	status := int32(4)
	cause := &profile.ClientFailure{Category: profile.FailureCategoryDeadline, GrpcStatus: &status,
		Message: "PRIVATE-PROVIDER-TOKEN", PlatformError: &profile.PlatformError{Message: "PRIVATE-PAYLOAD"}}
	value := FailureDiagnostic(&stepFailure{reason: "participant-blobGuest-rpc-failed", cause: cause})
	if value.Reason != "participant-blobguest-rpc-failed" || value.Category == nil || *value.Category != profile.FailureCategoryDeadline || value.GrpcStatus == nil || *value.GrpcStatus != 4 {
		t.Fatal("typed failure codes lost")
	}
	encoded, err := json.Marshal(value)
	if err != nil || strings.Contains(string(encoded), "PRIVATE") {
		t.Fatal("remote diagnostic exposed")
	}
	if raw := FailureDiagnostic(cause); raw.Reason != "participant-failed" {
		t.Fatal("peer error used as workflow label")
	}
	plain := FailureDiagnostic(errors.New("participant-blobGuest-pin-failed"))
	if plain.Reason != "participant-blobguest-pin-failed" || plain.Category != nil || plain.GrpcStatus != nil {
		t.Fatal("local assertion acquired protocol codes")
	}
}
