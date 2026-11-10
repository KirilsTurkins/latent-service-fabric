package transport

import (
	tx "latent.dev/sdk/go/transaction"
	"testing"
)

func TestInlineCommandOutcomeRequiresExactCommitAssociation(t *testing.T) {
	original := transactionInvokeFixture()
	command := transactionCommandFixture(tx.CommandOutcomeCommitted, true)
	command.Success.CommittedStateVersion = pointer("01")
	command.Success.EffectIds = []string{"effect-a"}
	invocation := transactionInvocationFixture(t, command)
	command.Success = nil
	response := tx.InvokeCommandResponse{Command: command, Invocation: invocation}
	if err := validateTransactionResponse(response, original, &callState{}); err != nil {
		t.Fatalf("valid inline commit: %v", err)
	}
	invocation.Success.CommittedStateVersion = pointer("02")
	if err := validateTransactionResponse(response, original, &callState{}); err == nil {
		t.Fatal("accepted mismatched committed version")
	}
	invocation.Success.CommittedStateVersion = pointer("01")
	invocation.Success.EffectIds = []string{"other-effect"}
	if err := validateTransactionResponse(response, original, &callState{}); err == nil {
		t.Fatal("accepted mismatched effect")
	}
	if err := validateTransactionResponse(tx.LookupCommandResponse{Command: command}, transactionLookupFixture(nil), &callState{}); err == nil {
		t.Fatal("lookup accepted missing retained body")
	}
	rejected := transactionCommandFixture(tx.CommandOutcomeRejected, true)
	rejectInvocation := transactionInvocationFixture(t, rejected)
	rejected.BusinessRejection = nil
	if err := validateTransactionResponse(tx.InvokeCommandResponse{Command: rejected, Invocation: rejectInvocation}, original, &callState{}); err != nil {
		t.Fatalf("valid inline rejection: %v", err)
	}
}
