package transport

import (
	"strings"
	"testing"

	"latent.dev/sdk/go/profile"
)

func TestStagingWitnessKeepsUnsignedScopeAndRejectsMalformedOriginalProgress(t *testing.T) {
	original := func() *profile.InspectActivationTreeResponse {
		return &profile.InspectActivationTreeResponse{
			SchemaVersion: 1, RetainedHistoryOnly: true, HistoryAvailable: true, Page: &profile.PageResponse{},
			Nodes: []profile.ActivationTreeNode{{
				ActivationId: "original", RootActivationId: "original", Phase: "running", ReceivedAtUnixMillis: 1000,
				GrantedBudget: &profile.ResourceBudget{EffectCount: 2, StateWriteBytes: ^uint64(0)},
				TransactionStaging: &profile.TransactionStagingWitness{
					SchemaVersion: 1, ActivationSerial: ^uint64(0), CommandId: strings.Repeat("1", 64),
					AttemptId: strings.Repeat("2", 64), TransactionId: strings.Repeat("3", 64),
					PublicationId: "publication:sha256:" + strings.Repeat("4", 64), StagedMutations: 2,
					CapturedIntents: 2, StateWriteBytes: ^uint64(0), ObservedAtUnixMillis: ^uint64(0),
				},
			}},
		}
	}
	request := profile.InspectActivationTreeRequest{ActivationId: "original"}
	if validateResponse(original(), request, &callState{}) != nil {
		t.Fatal("original maximum unsigned values were rejected")
	}
	absent := original()
	absent.Nodes[0].TransactionStaging = nil
	if validateResponse(absent, request, &callState{}) != nil {
		t.Fatal("absence became evidence or a decode failure")
	}
	for field := 0; field < 12; field++ {
		value := original()
		witness := value.Nodes[0].TransactionStaging
		switch field {
		case 0:
			witness.SchemaVersion = 2
		case 1:
			witness.ActivationSerial = 0
		case 2:
			witness.CommandId = strings.Repeat("A", 64)
		case 3:
			witness.AttemptId = "1"
		case 4:
			witness.TransactionId += "0"
		case 5:
			witness.PublicationId = strings.Repeat("4", 64)
		case 6:
			witness.StagedMutations = 129
		case 7:
			witness.CapturedIntents = 0
		case 8:
			witness.CapturedIntents = 3
		case 9:
			witness.StateWriteBytes = 0
		case 10:
			witness.ObservedAtUnixMillis = 999
		case 11:
			value.Nodes[0].GrantedBudget = nil
		}
		if validateResponse(value, request, &callState{}) == nil {
			t.Fatalf("malformed field %d was accepted", field)
		}
	}
}
