package transport

import (
	"bytes"
	"context"
	"encoding/base64"
	"errors"
	"math"
	"net/http"
	"reflect"
	"strings"
	"testing"

	"google.golang.org/protobuf/proto"
	latent "latent.dev/sdk/go"
	"latent.dev/sdk/go/internal/rpc/controlv1"
	"latent.dev/sdk/go/internal/rpc/invocationv1"
	"latent.dev/sdk/go/profile"
)

func TestEightGeneratedOperationsOneOwnedChannel(test *testing.T) {
	policy := &controlv1.Policy{Id: "policy-a", Metadata: &controlv1.ObjectMetadata{Name: "policy-a", Tenant: pointer("tenant-a")},
		Generation: math.MaxUint64, ContentDigest: "digest-a", RecordKind: controlv1.CapabilityPolicyRecordKind_CAPABILITY_POLICY_RECORD_KIND_POLICY,
		Language: "lsf-capability-policy-v1", Document: `{"full":18446744073709551615,"zero":0}`}
	receipt := &controlv1.CapabilityPolicyOperation{OperationId: "operation-a", Tenant: "tenant-a", Id: "policy-a", Generation: math.MaxUint64,
		ContentDigest: "digest-a", RecordKind: policy.RecordKind}
	peer := newPeer(test, func(writer http.ResponseWriter, request *http.Request) {
		switch request.URL.Path {
		case invocationv1.InvocationService_Invoke_FullMethodName:
			wire := &invocationv1.InvokeRequest{}
			decodePeerRequest(test, request, wire)
			if wire.ActivationId == nil || *wire.ActivationId != "activation-a" || wire.Budget.CpuFuel != math.MaxUint64 ||
				wire.Budget.WallTimeLimitMillis == nil || *wire.Budget.WallTimeLimitMillis != 0 || !bytes.Equal(wire.Payload, []byte{0, 255, 1, 128}) {
				test.Error("invocation request presence, full-width integers or raw bytes changed")
			}
			peerReply(writer, successWire("activation-a"))
		case invocationv1.InvocationService_Cancel_FullMethodName:
			wire := &invocationv1.CancelRequest{}
			decodePeerRequest(test, request, wire)
			peerReply(writer, &invocationv1.CancelResponse{Disposition: invocationv1.CancelDisposition_CANCEL_DISPOSITION_ALREADY_TERMINAL, TerminalState: pointer("completed")})
		case invocationv1.InvocationService_GetActivation_FullMethodName:
			wire := &invocationv1.GetActivationRequest{}
			decodePeerRequest(test, request, wire)
			peerReply(writer, &invocationv1.ActivationStatus{ActivationId: wire.ActivationId, Phase: "running", TerminalState: pointer("completed"),
				TerminalOutcome:  &invocationv1.ActivationStatus_Succeeded{Succeeded: &invocationv1.ActivationSuccessSummary{CommittedStateVersion: pointer("")}},
				FinalConsumption: &invocationv1.BudgetConsumption{BlobWriteBytes: math.MaxUint64}, TerminalAtUnixMillis: pointer(uint64(0))})
		case controlv1.PolicyService_GetPolicy_FullMethodName:
			wire := &controlv1.GetPolicyRequest{}
			decodePeerRequest(test, request, wire)
			peerReply(writer, &controlv1.GetPolicyResponse{Policy: policy})
		case controlv1.PolicyService_ListPolicies_FullMethodName:
			wire := &controlv1.ListPoliciesRequest{}
			decodePeerRequest(test, request, wire)
			if wire.Page == nil || wire.Page.PageSize != 1 || wire.Page.PageToken == nil || *wire.Page.PageToken != "opaque\x00cursor" {
				test.Error("policy page presence or opaque cursor changed")
			}
			peerReply(writer, &controlv1.ListPoliciesResponse{Policies: []*controlv1.Policy{policy}, CatalogGeneration: math.MaxUint64,
				Page: &controlv1.PageResponse{NextPageToken: pointer("")}})
		case controlv1.CapabilityService_ListCapabilities_FullMethodName:
			wire := &controlv1.ListCapabilitiesRequest{}
			decodePeerRequest(test, request, wire)
			peerReply(writer, &controlv1.ListCapabilitiesResponse{Capabilities: []*controlv1.CapabilityDescriptor{{Id: "capability-a",
				Inspection: &controlv1.CapabilityBindingInspection{ProviderConfigurationEpoch: math.MaxUint64,
					ProviderBinding: &controlv1.CapabilityInspectionPolicy{Id: "binding-a", Revision: math.MaxUint64}}}},
				Revision:    &controlv1.CapabilityInspectionRevision{DeploymentId: wire.DeploymentId, CatalogTransaction: math.MaxUint64},
				TenantUsage: &controlv1.CapabilityResourceUsage{Counters: map[string]uint64{"bytes": math.MaxUint64}, Unavailable: []string{"owner-absent"}}})
		case controlv1.PolicyService_ApplyPolicy_FullMethodName:
			wire := &controlv1.ApplyPolicyRequest{}
			decodePeerRequest(test, request, wire)
			if wire.ExpectedGeneration == nil || *wire.ExpectedGeneration != 0 || wire.OperationId != "operation-a" {
				test.Error("mutation precondition or recovery identity changed")
			}
			writer.Header().Set("latent-audit-status", "durable")
			writer.Header().Set("latent-audit-attempt", "18446744073709551615")
			peerReply(writer, &controlv1.ApplyPolicyResponse{Policy: policy, Receipt: receipt})
		case controlv1.PolicyService_GetPolicyOperation_FullMethodName:
			wire := &controlv1.GetPolicyOperationRequest{}
			decodePeerRequest(test, request, wire)
			peerReply(writer, &controlv1.GetPolicyOperationResponse{Receipt: receipt})
		default:
			test.Error("operation escaped the enumerated profile")
			peerFailure(writer, "12")
		}
	})
	client := testClient(test, peer)
	ctx := context.Background()
	input := invokeRequest("activation-a")
	invoked, failure := client.Invoke(ctx, input, profile.CallOptions{})
	if failure != nil || invoked.Value.RouteGeneration != math.MaxUint64 || invoked.Value.Consumption.CpuFuel != math.MaxUint64 ||
		invoked.Value.Success.CommittedStateVersion == nil || *invoked.Value.Success.CommittedStateVersion != "" ||
		!bytes.Equal(invoked.Value.Success.Payload, input.Payload) || invoked.Metadata.AuditAck != nil {
		test.Fatalf("lossless invocation failed: %v", failure)
	}
	input.Payload[0] = 7
	if invoked.Value.Success.Payload[0] != 0 {
		test.Fatal("request and response bytes alias")
	}
	cancelled, failure := client.Cancel(ctx, profile.CancelRequest{ActivationId: "activation-a"}, profile.CallOptions{})
	if failure != nil || cancelled.Value.Disposition != profile.CancelDispositionAlreadyTerminal {
		test.Fatalf("cancel disposition lost: %v", failure)
	}
	status, failure := client.GetActivation(ctx, profile.GetActivationRequest{ActivationId: "activation-a"}, profile.CallOptions{})
	if failure != nil || status.Value.TerminalAtUnixMillis == nil || *status.Value.TerminalAtUnixMillis != 0 || status.Value.FinalConsumption.BlobWriteBytes != math.MaxUint64 {
		test.Fatalf("retained terminal response lost: %v", failure)
	}
	read, failure := client.GetPolicy(ctx, profile.GetPolicyRequest{Id: "policy-a", RecordKind: profile.CapabilityPolicyRecordKindPolicy}, profile.CallOptions{})
	if failure != nil || read.Value.Policy.Generation != math.MaxUint64 || read.Value.Policy.Document != policy.Document {
		test.Fatalf("policy record lost: %v", failure)
	}
	page, failure := client.ListPolicies(ctx, profile.ListPoliciesRequest{RecordKind: profile.CapabilityPolicyRecordKindPolicy,
		Page: &profile.PageRequest{PageSize: 1, PageToken: pointer("opaque\x00cursor")}}, profile.CallOptions{})
	if failure != nil || page.Value.CatalogGeneration != math.MaxUint64 || page.Value.Page.NextPageToken == nil || *page.Value.Page.NextPageToken != "" {
		test.Fatalf("page response lost: %v", failure)
	}
	capabilities, failure := client.ListCapabilities(ctx, profile.ListCapabilitiesRequest{DeploymentId: "deployment-a", Page: &profile.PageRequest{PageSize: 1}}, profile.CallOptions{})
	if failure != nil || capabilities.Value.TenantUsage.Counters["bytes"] != math.MaxUint64 ||
		capabilities.Value.Capabilities[0].Inspection.ProviderConfigurationEpoch != math.MaxUint64 || capabilities.Value.NodeUsage != nil {
		test.Fatalf("redacted provider inspection lost: %v", failure)
	}
	applied, failure := client.ApplyPolicy(ctx, policyRequest(), profile.CallOptions{})
	if failure != nil || applied.Metadata.AuditAck == nil || *applied.Metadata.AuditAck.AttemptSequence != math.MaxUint64 ||
		applied.Value.Receipt.Generation != math.MaxUint64 || applied.Metadata.Outcome != profile.OutcomeKnowledgeObserved {
		test.Fatalf("mutation receipt or audit acknowledgement lost: %v", failure)
	}
	recovered, failure := client.GetPolicyOperation(ctx, profile.GetPolicyOperationRequest{OperationId: "operation-a"}, profile.CallOptions{})
	if failure != nil || !reflect.DeepEqual(recovered.Value.Receipt, applied.Value.Receipt) || recovered.Metadata.AuditAck != nil {
		test.Fatalf("operation recovery changed: %v", failure)
	}
	if peer.accepted.Load() != 1 || peer.requests.Load() != 8 {
		test.Fatal("client connected, retried or paginated implicitly")
	}
}

func policyRequest() profile.ApplyPolicyRequest {
	return profile.ApplyPolicyRequest{OperationId: "operation-a", ExpectedGeneration: pointer(uint64(0)),
		Policy: &profile.Policy{Id: "policy-a", Metadata: &profile.ObjectMetadata{Name: "policy-a", Tenant: pointer("tenant-a")},
			RecordKind: profile.CapabilityPolicyRecordKindPolicy, Language: "lsf-capability-policy-v1", Document: `{"formatVersion":1,"tenant":"tenant-a","rules":[]}`}}
}

func TestLegacyOutcomeAndRawPlatformStatus(test *testing.T) {
	peer := newPeer(test, func(writer http.ResponseWriter, request *http.Request) {
		wire := &invocationv1.InvokeRequest{}
		decodePeerRequest(test, request, wire)
		response := successWire(*wire.ActivationId)
		switch wire.Target.Function {
		case "declared":
			response.Result = &invocationv1.InvokeResponse_DeclaredError{DeclaredError: &invocationv1.DeclaredError{Code: "uncertain", Payload: []byte{255, 0}}}
		case "platform":
			response.Result = &invocationv1.InvokeResponse_PlatformFailure{PlatformFailure: &invocationv1.PlatformError{
				Code: "permission-denied", DetailItems: []*invocationv1.ErrorDetail{{Kind: "provider", Fields: map[string]string{"state": "revoked"}}}}}
		case "rpc":
			detail, _ := proto.Marshal(&controlv1.PlatformError{Code: "state-conflict", Message: "safe " + fixtureToken,
				DetailItems: []*controlv1.ErrorDetail{{Kind: "precondition", Fields: map[string]string{"generation": "18446744073709551615"}}}})
			writer.Header().Set("grpc-status-details-bin", base64.RawStdEncoding.EncodeToString(detail))
			writer.Header().Set("latent-audit-status", "future-audit-status")
			peerFailure(writer, "9")
			return
		}
		peerReply(writer, response)
	})
	client := testClient(test, peer)
	for _, kind := range []string{"success", "declared", "platform"} {
		request := latent.InvokeRequest{ActivationID: pointer("legacy-a"), Target: latent.Target{Tenant: "tenant-a", Function: kind}}
		response, failure := client.Legacy().Invoke(context.Background(), request)
		if failure != nil || (kind == "success" && response.Success == nil) || (kind == "declared" && response.DeclaredError == nil) ||
			(kind == "platform" && (response.PlatformFailure == nil || response.PlatformFailure.Error.Details[0].Fields["state"] != "revoked")) {
			test.Fatalf("legacy outcome %s lost: %v", kind, failure)
		}
	}
	request := invokeRequest("rpc-a")
	request.Target.Function = "rpc"
	_, failure := client.Invoke(context.Background(), request, profile.CallOptions{})
	var detail *profile.ClientFailure
	if !errors.As(failure, &detail) || detail.GrpcStatus == nil || *detail.GrpcStatus != 9 || detail.PlatformError == nil ||
		detail.PlatformError.Code != "state-conflict" || strings.Contains(detail.PlatformError.Message, fixtureToken) ||
		detail.PlatformError.DetailItems[0].Fields["generation"] != "18446744073709551615" ||
		detail.AuditStatus == nil || *detail.AuditStatus != "future-audit-status" || detail.AuditAck != nil {
		test.Fatalf("raw RPC status, structured error, audit or redaction lost: %v", failure)
	}
}
