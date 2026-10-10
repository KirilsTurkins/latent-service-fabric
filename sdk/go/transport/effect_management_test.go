package transport

import (
	"bytes"
	"context"
	"latent.dev/sdk/go/internal/rpc/statev1"
	"latent.dev/sdk/go/profile"
	tx "latent.dev/sdk/go/transaction"
	"math"
	"net/http"
	"strings"
	"testing"
)

func transactionEffectMutationFixture() tx.PlanEffectMutationRequest {
	_, command, inspect := transactionFixtures()
	return tx.PlanEffectMutationRequest{Effect: &tx.GetEffectRequest{Profile: inspect.Profile, Command: &command, EffectId: strings.Repeat("a", 64), AuthorizationPublication: inspect.AuthorizationPublication},
		OperationId: "effect-operation-a", Mutation: tx.StateMutationKindRetryKnownFailedEffect, ExpectedVersion: bytes.Repeat([]byte{1}, 32), ExpectedPolicyDigest: transactionSourceFixture().StateSchema, Reason: "explicit redrive", RetryDelayMillis: 100}
}
func transactionEffectPlanFixture(original tx.PlanEffectMutationRequest) tx.EffectManagementPlan {
	return tx.EffectManagementPlan{Original: &original, PlanDigest: bytes.Repeat([]byte{2}, 32), ManagementSequence: 1, OwnerEpoch: math.MaxUint64, ClaimGeneration: 1, DispatchAttempt: 1,
		PreparedAtUnixMillis: 1000, ExpiresAtUnixMillis: 2000, Before: tx.EffectDispositionKnownFailure, Safety: tx.EffectPlanSafetyKnownNonexecution}
}
func transactionEffectReceiptFixture(plan *tx.EffectManagementPlan) tx.StateOperationReceipt {
	original := plan.Original
	return tx.StateOperationReceipt{OperationId: original.OperationId, ReceiptId: "effect-management-receipt", Mutation: original.Mutation, Namespace: original.Effect.Command.Namespace,
		AuthenticatedOperator: "operator-a", BeforeVersion: original.ExpectedVersion, AfterVersion: bytes.Repeat([]byte{3}, 32), CompletedAtUnixMillis: 1500, RecordId: &original.Effect.EffectId,
		PolicyDigest: original.ExpectedPolicyDigest, Disposition: tx.StateOperationDispositionCommitted, Effect: &tx.EffectManagementReceiptDetails{OriginalPlan: plan, Before: plan.Before, After: tx.EffectDispositionRetryScheduled, Fact: tx.EffectManagementFactRedriveScheduled}}
}

// Historical receipt recovery and independent audit facts execute through the real channel.
func TestTransactionEffectPlansKeepOriginalCasAndIndependentFacts(test *testing.T) {
	peer := newPeer(test, func(writer http.ResponseWriter, request *http.Request) {
		switch request.URL.Path[strings.LastIndex(request.URL.Path, "/")+1:] {
		case "PlanEffectMutation":
			wire := &statev1.PlanEffectMutationRequest{}
			decodePeerRequest(test, request, wire)
			original := tx.PlanEffectMutationRequest{}
			if failure := fromProto(wire, &original); failure != nil {
				test.Error(failure)
			}
			plan := transactionEffectPlanFixture(original)
			if original.Reason == "bad-window" {
				plan.ExpiresAtUnixMillis = 31001
			}
			response := tx.PlanEffectMutationResponse{Plan: &plan}
			if original.Reason == "bad-audit" {
				response.AuditAck = &profile.AuditAck{Status: profile.AuditAckStatus(91)}
			}
			peerReply(writer, transactionWireFixture(test, response, &statev1.PlanEffectMutationResponse{}))
		case "MutateState":
			wire := &statev1.MutateStateRequest{}
			decodePeerRequest(test, request, wire)
			original := tx.MutateStateRequest{}
			if failure := fromProto(wire, &original); failure != nil {
				test.Error(failure)
			}
			receipt := transactionEffectReceiptFixture(original.EffectPlan)
			if original.Reason == "forged-fact" {
				receipt.Effect.Fact = tx.EffectManagementFactProviderConfirmed
				receipt.Effect.ProviderReceipt = pointer("forged-provider")
				receipt.Effect.ProviderObservedAtUnixMillis = pointer(uint64(1400))
			}
			peerReply(writer, transactionWireFixture(test, tx.MutateStateResponse{Receipt: &receipt}, &statev1.MutateStateResponse{}))
		case "GetStateOperationReceipt":
			wire := &statev1.GetStateOperationReceiptRequest{}
			decodePeerRequest(test, request, wire)
			original := tx.GetStateOperationReceiptRequest{}
			if failure := fromProto(wire, &original); failure != nil {
				test.Error(failure)
			}
			if original.Namespace.AuthorizationPublication.Id == original.OriginalEffectPlan.Original.Effect.AuthorizationPublication.Id {
				test.Error("fresh authority rewrote original plan")
			}
			peerReply(writer, transactionWireFixture(test, tx.GetStateOperationReceiptResponse{Receipt: pointer(transactionEffectReceiptFixture(original.OriginalEffectPlan))}, &statev1.GetStateOperationReceiptResponse{}))
		default:
			test.Error("unexpected effect operation")
		}
	})
	client := testClient(test, peer)
	ctx, options := context.Background(), profile.CallOptions{}
	prepared, failure := client.PlanEffectMutation(ctx, transactionEffectMutationFixture(), options)
	if failure != nil {
		test.Fatal(failure)
	}
	if prepared.Metadata.Transport.Outcome != profile.OutcomeKnowledgeUnknown || prepared.Metadata.Identity.EffectPlan == nil {
		test.Fatal("plan supplied accepted mutation knowledge")
	}
	plan, original := prepared.Value.Plan, prepared.Value.Plan.Original
	_, _, inspect := transactionFixtures()
	mutation := tx.MutateStateRequest{Namespace: &inspect, OperationId: original.OperationId, Mutation: original.Mutation, RecordId: &original.Effect.EffectId,
		ExpectedVersion: original.ExpectedVersion, ExpectedPolicyDigest: original.ExpectedPolicyDigest, Reason: original.Reason, EffectPlan: plan}
	accepted, failure := client.MutateState(ctx, mutation, options)
	if failure != nil || accepted.Metadata.Transport.Outcome != profile.OutcomeKnowledgeObserved || accepted.Value.Receipt.Effect.Fact != tx.EffectManagementFactRedriveScheduled {
		test.Fatal("redrive receipt became provider confirmation", failure)
	}
	current := inspect
	current.AuthorizationPublication = &profile.PublicationRef{Id: "publication:sha256:" + strings.Repeat("c", 64), Tenant: "tenant-a"}
	recovered, failure := client.GetStateOperationReceipt(ctx, tx.GetStateOperationReceiptRequest{Namespace: &current, OperationId: original.OperationId, OriginalEffectPlan: plan}, options)
	if failure != nil || recovered.Metadata.Identity.AuthorizationPublication.Id != current.AuthorizationPublication.Id || recovered.Metadata.Identity.EffectMutation.Effect.AuthorizationPublication.Id != inspect.AuthorizationPublication.Id {
		test.Fatal("historical recovery refreshed original policy identity", failure)
	}
	mutation.EffectPlan = nil
	_, failure = client.MutateState(ctx, mutation, options)
	if transactionFailureFixture(test, failure, profile.FailureCategoryInvalidRequest).Transport.Dispatched {
		test.Fatal("naked effect mutation dispatched")
	}
	mutation.EffectPlan = plan
	mutation.ExpectedVersion = make([]byte, 32)
	_, failure = client.MutateState(ctx, mutation, options)
	if transactionFailureFixture(test, failure, profile.FailureCategoryInvalidRequest).Transport.Dispatched {
		test.Fatal("substituted CAS dispatched")
	}
	audit := transactionEffectMutationFixture()
	audit.Reason = "bad-audit"
	_, failure = client.PlanEffectMutation(ctx, audit, options)
	observed := transactionFailureFixture(test, failure, profile.FailureCategoryDecode)
	if observed.Transport.Outcome != profile.OutcomeKnowledgeUnknown || observed.Observed.EffectPlan == nil || observed.Identity.EffectPlan.Original.Reason != "bad-audit" {
		test.Fatal("audit erased checked plan or made mutation known")
	}
	audit.Reason = "bad-window"
	_, failure = client.PlanEffectMutation(ctx, audit, options)
	if transactionFailureFixture(test, failure, profile.FailureCategoryDecode).Observed != nil {
		test.Fatal("invalid plan supplied proof")
	}
	audit.Reason = "forged-fact"
	forged := transactionEffectPlanFixture(audit)
	mutation.EffectPlan = &forged
	mutation.ExpectedVersion = audit.ExpectedVersion
	mutation.Reason = audit.Reason
	_, failure = client.MutateState(ctx, mutation, options)
	if transactionFailureFixture(test, failure, profile.FailureCategoryDecode).Observed != nil || peer.requests.Load() != 6 || peer.accepted.Load() != 1 {
		test.Fatal("provider fact invented or operation replayed")
	}
}
