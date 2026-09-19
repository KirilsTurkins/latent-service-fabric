package transport

import (
	"context"
	"encoding/binary"
	"errors"
	"math"
	"net/http"
	"strings"
	"sync"
	"sync/atomic"
	"testing"

	"google.golang.org/grpc/metadata"
	"google.golang.org/protobuf/proto"
	"latent.dev/sdk/go/internal/rpc/controlv1"
	"latent.dev/sdk/go/internal/rpc/invocationv1"
	"latent.dev/sdk/go/profile"
)

func TestControlledMalformedAndOversizedResponses(test *testing.T) {
	valid, failure := proto.Marshal(successWire("wire-a"))
	if failure != nil {
		test.Fatal(failure)
	}
	oversized := make([]byte, 5)
	binary.BigEndian.PutUint32(oversized[1:], 1024*1024+1)
	cases := []struct {
		name     string
		category profile.FailureCategory
		reply    http.HandlerFunc
	}{
		{"malformed-protobuf", profile.FailureCategoryDecode, func(writer http.ResponseWriter, request *http.Request) {
			peerBytes(writer, frame([]byte{10, 255}), "0")
		}},
		{"contradictory-oneof", profile.FailureCategoryDecode, func(writer http.ResponseWriter, request *http.Request) {
			peerBytes(writer, frame(append(append([]byte(nil), valid...), 66, 0)), "0")
		}},
		{"oversized-frame-prefix", profile.FailureCategoryLimit, func(writer http.ResponseWriter, request *http.Request) { peerBytes(writer, oversized, "0") }},
		{"extra-unary-frame", profile.FailureCategoryDecode, func(writer http.ResponseWriter, request *http.Request) {
			peerBytes(writer, append(frame(valid), frame(valid)...), "0")
		}},
		{"compressed-flag", profile.FailureCategoryDecode, func(writer http.ResponseWriter, request *http.Request) {
			packet := frame(valid)
			packet[0] = 1
			peerBytes(writer, packet, "0")
		}},
		{"compression-header", profile.FailureCategoryDecode, func(writer http.ResponseWriter, request *http.Request) {
			writer.Header().Set("grpc-encoding", "gzip")
			peerBytes(writer, frame(valid), "0")
		}},
		{"missing-message", profile.FailureCategoryDecode, func(writer http.ResponseWriter, request *http.Request) { peerFailure(writer, "0") }},
		{"missing-status", profile.FailureCategoryDecode, func(writer http.ResponseWriter, request *http.Request) {
			writer.Header().Set("content-type", "application/grpc")
			_, _ = writer.Write(frame(valid))
		}},
		{"duplicate-status", profile.FailureCategoryDecode, func(writer http.ResponseWriter, request *http.Request) {
			writer.Header().Set("grpc-status", "0")
			peerBytes(writer, frame(valid), "0")
		}},
		{"invalid-status", profile.FailureCategoryDecode, func(writer http.ResponseWriter, request *http.Request) { peerBytes(writer, frame(valid), "not-a-code") }},
		{"audit-overflow", profile.FailureCategoryDecode, func(writer http.ResponseWriter, request *http.Request) {
			writer.Header().Set("latent-audit-status", "durable")
			writer.Header().Set("latent-audit-attempt", "18446744073709551616")
			peerBytes(writer, frame(valid), "0")
		}},
		{"audit-duplicate", profile.FailureCategoryDecode, func(writer http.ResponseWriter, request *http.Request) {
			writer.Header().Add("latent-audit-status", "durable")
			writer.Header().Add("latent-audit-status", "disabled")
			peerBytes(writer, frame(valid), "0")
		}},
		{"header-limit", profile.FailureCategoryTransport, func(writer http.ResponseWriter, request *http.Request) {
			writer.Header().Set("large", strings.Repeat("a", 17*1024))
			peerBytes(writer, frame(valid), "0")
		}},
		{"no-redirect-follow", profile.FailureCategoryDecode, func(writer http.ResponseWriter, request *http.Request) {
			writer.Header().Set("location", "http://127.0.0.1:1/unapproved")
			writer.WriteHeader(307)
		}},
		{"wrong-content-type", profile.FailureCategoryDecode, func(writer http.ResponseWriter, request *http.Request) {
			writer.Header().Set("content-type", "application/json")
			writer.Header().Set("grpc-status", "0")
			_, _ = writer.Write(frame(valid))
		}},
	}
	for _, scenario := range cases {
		test.Run(scenario.name, func(test *testing.T) {
			peer := newPeer(test, scenario.reply)
			client := testClient(test, peer)
			_, failure := client.Invoke(context.Background(), invokeRequest("wire-a"), profile.CallOptions{})
			detail := assertFailure(test, failure, scenario.category, true)
			if detail.Identity.ActivationId == nil || *detail.Identity.ActivationId != "wire-a" || peer.requests.Load() != 1 {
				test.Fatal("malformed response lost identity or caused resubmission")
			}
		})
	}
}

func TestNilEmptyIdentityFullWidthDeadlineAndNoAmbientAuthority(test *testing.T) {
	seen := make(chan *string, 2)
	peer := newPeer(test, func(writer http.ResponseWriter, request *http.Request) {
		wire := &invocationv1.InvokeRequest{}
		decodePeerRequest(test, request, wire)
		seen <- wire.ActivationId
		if wire.DeadlineUnixMillis == nil || *wire.DeadlineUnixMillis != math.MaxUint64 || wire.RootActivationId == nil || *wire.RootActivationId != "" {
			test.Error("absolute deadline or lineage was normalized")
		}
		if wire.ActivationId == nil {
			peerReply(writer, successWire("server-assigned"))
		} else {
			peerFailure(writer, "3")
		}
	})
	client := testClient(test, peer)
	request := invokeRequest("unused")
	request.ActivationId = nil
	request.RootActivationId = pointer("")
	request.DeadlineUnixMillis = pointer(uint64(math.MaxUint64))
	ctx := metadata.NewOutgoingContext(context.Background(), metadata.Pairs("authorization", "Bearer untrusted", "x-principal", "operator"))
	response, failure := client.Invoke(ctx, request, profile.CallOptions{})
	if failure != nil || response.Metadata.Identity.ActivationId == nil || *response.Metadata.Identity.ActivationId != "server-assigned" {
		test.Fatalf("absent identity or explicit credential changed: %v", failure)
	}
	request.ActivationId = pointer("")
	_, failure = client.Invoke(ctx, request, profile.CallOptions{})
	detail := assertFailure(test, failure, profile.FailureCategoryRpc, true)
	first, second := <-seen, <-seen
	if detail.Identity.ActivationId == nil || *detail.Identity.ActivationId != "" || first != nil || second == nil || *second != "" {
		test.Fatal("present-invalid identity became absent")
	}
}

func TestLostMutationRequiresOriginalIDRecoveryAndExplicitReplay(test *testing.T) {
	var mutex sync.Mutex
	var retained *controlv1.ApplyPolicyRequest
	var attempts atomic.Int64
	receipt := &controlv1.CapabilityPolicyOperation{OperationId: "operation-a", Tenant: "tenant-a", Id: "policy-a", Generation: 1,
		ContentDigest: "digest-a", RecordKind: controlv1.CapabilityPolicyRecordKind_CAPABILITY_POLICY_RECORD_KIND_POLICY}
	peer := newPeer(test, func(writer http.ResponseWriter, request *http.Request) {
		if request.URL.Path == controlv1.PolicyService_GetPolicyOperation_FullMethodName {
			wire := &controlv1.GetPolicyOperationRequest{}
			decodePeerRequest(test, request, wire)
			if wire.OperationId != "operation-a" {
				test.Error("lost mutation recovery changed the operation ID")
			}
			peerReply(writer, &controlv1.GetPolicyOperationResponse{Receipt: receipt})
			return
		}
		wire := &controlv1.ApplyPolicyRequest{}
		decodePeerRequest(test, request, wire)
		mutex.Lock()
		attempts.Add(1)
		first := retained == nil
		if first {
			retained = proto.Clone(wire).(*controlv1.ApplyPolicyRequest)
		}
		same := proto.Equal(retained, wire)
		mutex.Unlock()
		if first {
			panic(http.ErrAbortHandler)
		}
		if !same {
			peerFailure(writer, "9")
			return
		}
		policy := proto.Clone(wire.Policy).(*controlv1.Policy)
		policy.Generation = 1
		policy.ContentDigest = "digest-a"
		peerReply(writer, &controlv1.ApplyPolicyResponse{Policy: policy, Receipt: receipt})
	})
	client := testClient(test, peer)
	request := policyRequest()
	_, failure := client.ApplyPolicy(context.Background(), request, profile.CallOptions{})
	detail := assertFailure(test, failure, profile.FailureCategoryTransport, true)
	if detail.Identity.OperationId == nil || *detail.Identity.OperationId != "operation-a" {
		test.Fatal("lost mutation identity was not retained")
	}
	lookup, failure := client.GetPolicyOperation(context.Background(), profile.GetPolicyOperationRequest{OperationId: "operation-a"}, profile.CallOptions{})
	if failure != nil || lookup.Value.Receipt.Generation != 1 || attempts.Load() != 1 {
		test.Fatalf("recovery silently replayed: %v", failure)
	}
	_, failure = client.ApplyPolicy(context.Background(), request, profile.CallOptions{})
	if failure != nil || attempts.Load() != 2 {
		test.Fatalf("explicit identical replay failed: %v", failure)
	}
	request.Policy.Document = `{"changed":true}`
	_, failure = client.ApplyPolicy(context.Background(), request, profile.CallOptions{})
	detail = assertFailure(test, failure, profile.FailureCategoryRpc, true)
	if detail.GrpcStatus == nil || *detail.GrpcStatus != 9 || attempts.Load() != 3 || peer.accepted.Load() != 1 {
		test.Fatal("changed replay conflict or single-channel ownership lost")
	}
}

func TestNotFoundUnknownCancellationDispositionsAndOpenManagementEnums(test *testing.T) {
	peer := newPeer(test, func(writer http.ResponseWriter, request *http.Request) {
		switch request.URL.Path {
		case invocationv1.InvocationService_Cancel_FullMethodName:
			wire := &invocationv1.CancelRequest{}
			decodePeerRequest(test, request, wire)
			disposition := invocationv1.CancelDisposition_CANCEL_DISPOSITION_ACCEPTED
			var terminal *string
			if wire.Reason == "terminal" {
				disposition = invocationv1.CancelDisposition_CANCEL_DISPOSITION_ALREADY_TERMINAL
				terminal = pointer("completed")
			} else if wire.Reason == "missing" {
				disposition = invocationv1.CancelDisposition_CANCEL_DISPOSITION_NOT_FOUND
			}
			peerReply(writer, &invocationv1.CancelResponse{Disposition: disposition, TerminalState: terminal})
		case invocationv1.InvocationService_GetActivation_FullMethodName:
			peerFailure(writer, "5")
		case controlv1.PolicyService_GetPolicyOperation_FullMethodName:
			peerReply(writer, &controlv1.GetPolicyOperationResponse{})
		case controlv1.PolicyService_GetPolicy_FullMethodName:
			peerReply(writer, &controlv1.GetPolicyResponse{Policy: &controlv1.Policy{Id: "future", RecordKind: -2147483648, Generation: math.MaxUint64}})
		}
	})
	client := testClient(test, peer)
	for index, reason := range []string{"accepted", "terminal", "missing"} {
		response, failure := client.Cancel(context.Background(), profile.CancelRequest{ActivationId: "known-a", Reason: reason}, profile.CallOptions{})
		if failure != nil || int(response.Value.Disposition) != index+1 || (reason == "missing" && response.Metadata.Outcome != profile.OutcomeKnowledgeUnknown) {
			test.Fatalf("cancellation disposition collapsed: %v", failure)
		}
	}
	_, failure := client.GetActivation(context.Background(), profile.GetActivationRequest{ActivationId: "known-a"}, profile.CallOptions{})
	detail := assertFailure(test, failure, profile.FailureCategoryRpc, true)
	if detail.GrpcStatus == nil || *detail.GrpcStatus != 5 {
		test.Fatal("bounded not-found did not retain RPC status")
	}
	recovery, failure := client.GetPolicyOperation(context.Background(), profile.GetPolicyOperationRequest{OperationId: "operation-a"}, profile.CallOptions{})
	if failure != nil || recovery.Value.Receipt != nil || recovery.Metadata.Outcome != profile.OutcomeKnowledgeUnknown {
		test.Fatal("absent receipt was treated as nonexecution")
	}
	policy, failure := client.GetPolicy(context.Background(), profile.GetPolicyRequest{Id: "future", RecordKind: profile.CapabilityPolicyRecordKindProviderBinding}, profile.CallOptions{})
	if failure != nil || policy.Value.Policy.RecordKind != -2147483648 || policy.Value.Policy.Generation != math.MaxUint64 {
		test.Fatal("future management enum or full-width generation collapsed")
	}
}

func TestUnsupportedInvocationValuesRetainEvidence(test *testing.T) {
	peer := newPeer(test, func(writer http.ResponseWriter, request *http.Request) {
		peerReply(writer, &invocationv1.CancelResponse{Disposition: -2147483648})
	})
	client := testClient(test, peer)
	_, failure := client.Cancel(context.Background(), profile.CancelRequest{ActivationId: "known-a"}, profile.CallOptions{})
	detail := assertFailure(test, failure, profile.FailureCategoryDecode, true)
	if detail.UnsupportedWireValue == nil || detail.UnsupportedWireValue.Value != "-2147483648" || detail.Identity.ActivationId == nil {
		test.Fatal("unsupported enum evidence or original identity lost")
	}
}

func TestRequestBoundsAndMutationPreconditionsBeforeDispatch(test *testing.T) {
	peer := newPeer(test, func(writer http.ResponseWriter, request *http.Request) {
		test.Error("invalid bounded request was dispatched")
	})
	client := testClient(test, peer, func(config *Config) { config.MaxRequestBytes = 32 })
	request := policyRequest()
	request.ExpectedGeneration = nil
	_, failure := client.ApplyPolicy(context.Background(), request, profile.CallOptions{})
	assertFailure(test, failure, profile.FailureCategoryInvalidRequest, false)
	_, failure = client.GetPolicy(context.Background(), profile.GetPolicyRequest{Id: strings.Repeat("a", 64), RecordKind: profile.CapabilityPolicyRecordKindPolicy}, profile.CallOptions{})
	assertFailure(test, failure, profile.FailureCategoryLimit, false)
	_, failure = client.ListPolicies(context.Background(), profile.ListPoliciesRequest{RecordKind: profile.CapabilityPolicyRecordKindPolicy, Page: &profile.PageRequest{PageSize: 0}}, profile.CallOptions{})
	assertFailure(test, failure, profile.FailureCategoryInvalidRequest, false)
	_, failure = client.ListCapabilities(context.Background(), profile.ListCapabilitiesRequest{DeploymentId: "deployment-a", Page: &profile.PageRequest{PageSize: 129}}, profile.CallOptions{})
	assertFailure(test, failure, profile.FailureCategoryInvalidRequest, false)
	if peer.requests.Load() != 0 {
		test.Fatal("invalid request reached a peer")
	}
	for _, endpoint := range []string{"https://127.0.0.1:1", "http://localhost:1", "http://192.0.2.1:1", "http://127.0.0.1:1/", "http://127.0.0.1:1?authority=operator", "http://user@127.0.0.1:1"} {
		_, failure := New(context.Background(), DefaultConfig(endpoint, fixtureToken))
		var detail *profile.ClientFailure
		if !errors.As(failure, &detail) || detail.Category != profile.FailureCategoryInvalidRequest {
			test.Fatal("unsupported endpoint profile accepted")
		}
	}
}
