package transport

import (
	"context"
	"errors"
	"math"
	"net/http"
	"reflect"
	"testing"

	"latent.dev/sdk/go/internal/rpc/controlv1"
	"latent.dev/sdk/go/profile"
)

func TestIndependentAuditMetadataOnSuccessAndFailure(test *testing.T) {
	cases := []struct {
		name    string
		status  *string
		attempt *string
		expect  profile.ResponseMetadata
	}{
		{name: "absent"},
		{name: "durable-max", status: pointer("durable"), attempt: pointer("18446744073709551615"), expect: profile.ResponseMetadata{
			AuditStatus: pointer("durable"), AuditAttemptSequence: pointer(uint64(math.MaxUint64)),
			AuditAck: &profile.AuditAck{Status: profile.AuditAckStatusDurable, AttemptSequence: pointer(uint64(math.MaxUint64))}}},
		{name: "outcome-unknown", status: pointer("outcome-unknown"), attempt: pointer("12"), expect: profile.ResponseMetadata{
			AuditStatus: pointer("outcome-unknown"), AuditAttemptSequence: pointer(uint64(12)),
			AuditAck: &profile.AuditAck{Status: profile.AuditAckStatusOutcomeUnknown, AttemptSequence: pointer(uint64(12))}}},
		{name: "unavailable", status: pointer("audit-unavailable"), expect: profile.ResponseMetadata{
			AuditStatus: pointer("audit-unavailable"), AuditAck: &profile.AuditAck{Status: profile.AuditAckStatusAuditUnavailable}}},
		{name: "disabled-zero", status: pointer("disabled"), attempt: pointer("0"), expect: profile.ResponseMetadata{
			AuditStatus: pointer("disabled"), AuditAttemptSequence: pointer(uint64(0)),
			AuditAck: &profile.AuditAck{Status: profile.AuditAckStatusDisabled, AttemptSequence: pointer(uint64(0))}}},
		{name: "future-max", status: pointer("future-state"), attempt: pointer("18446744073709551615"), expect: profile.ResponseMetadata{
			AuditStatus: pointer("future-state"), AuditAttemptSequence: pointer(uint64(math.MaxUint64))}},
		{name: "future-without-attempt", status: pointer("future-state"), expect: profile.ResponseMetadata{AuditStatus: pointer("future-state")}},
		{name: "attempt-without-status", attempt: pointer("18446744073709551615"), expect: profile.ResponseMetadata{AuditAttemptSequence: pointer(uint64(math.MaxUint64))}},
	}
	for _, scenario := range cases {
		for _, status := range []string{"0", "9"} {
			test.Run(scenario.name+"/rpc-"+status, func(test *testing.T) {
				peer := newPeer(test, func(writer http.ResponseWriter, request *http.Request) {
					if scenario.status != nil {
						writer.Header().Set("latent-audit-status", *scenario.status)
					}
					if scenario.attempt != nil {
						writer.Header().Set("latent-audit-attempt", *scenario.attempt)
					}
					if status == "9" {
						peerFailure(writer, status)
						return
					}
					peerReply(writer, &controlv1.GetPolicyOperationResponse{Receipt: &controlv1.CapabilityPolicyOperation{OperationId: "operation-a"}})
				})
				client := testClient(test, peer)
				response, failure := client.GetPolicyOperation(context.Background(), profile.GetPolicyOperationRequest{OperationId: "operation-a"}, profile.CallOptions{})
				observed := response.Metadata
				outcome := profile.OutcomeKnowledgeObserved
				if status == "9" {
					var detail *profile.ClientFailure
					if !errors.As(failure, &detail) || detail.GrpcStatus == nil || *detail.GrpcStatus != 9 {
						test.Fatalf("RPC failure lost: %v", failure)
					}
					observed = profile.ResponseMetadata{Identity: detail.Identity, Outcome: detail.Outcome,
						AuditAck: detail.AuditAck, AuditStatus: detail.AuditStatus, AuditAttemptSequence: detail.AuditAttemptSequence}
					outcome = profile.OutcomeKnowledgeUnknown
				} else if failure != nil {
					test.Fatalf("audit data changed a successful receipt: %v", failure)
				}
				expected := scenario.expect
				expected.Identity.OperationId = pointer("operation-a")
				expected.Outcome = outcome
				if !reflect.DeepEqual(expected, observed) {
					test.Fatalf("audit facts were inferred or lost: got %#v, want %#v", observed, expected)
				}
			})
		}
	}
}
