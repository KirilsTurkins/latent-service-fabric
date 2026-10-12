package transport

import (
	"context"
	"latent.dev/sdk/go/internal/rpc/controlv1"
	"latent.dev/sdk/go/profile"
	"math"
	"net/http"
	"strings"
	"testing"
)

func TestTargetInspectionUsesGeneratedRPCAndBoundedOriginalSelectors(test *testing.T) {
	peer := newPeer(test, func(writer http.ResponseWriter, request *http.Request) {
		if request.URL.Path != "/latent.control.v1.NodeService/InspectHttpTarget" {
			test.Error("target used another RPC")
		}
		input := &controlv1.InspectHttpTargetRequest{}
		decodePeerRequest(test, request, input)
		response := &controlv1.InspectHttpTargetResponse{SchemaVersion: 1, Tenant: "tenant-a", Service: input.Service, Contract: input.Contract, Function: input.Function, Route: "default", State: 1, CatalogTransaction: math.MaxUint64,
			Candidates: []*controlv1.TargetCandidate{{DeploymentId: "deployment-a", RevisionId: "revision-a", ComponentDigest: "sha256:" + strings.Repeat("a", 64), Publication: input.Publication,
				Reasons: []controlv1.TargetReason{777}, Preparation: &controlv1.TargetPreparation{State: 3}}}}
		if input.Function == "foreign" {
			response.Tenant = "foreign"
		}
		if input.Function == "drift" {
			response.Candidates[0].RevisionId = "revision-b"
		}
		if input.Function == "future" {
			response.State = 777
			response.Candidates[0].Preparation.State = 779
		}
		peerReply(writer, response)
	})
	client := testClient(test, peer)
	input := profile.InspectHttpTargetRequest{Service: "service-a", Contract: "domain:api/contract@1.0.0", Function: "get", RevisionId: pointer("revision-a"), IncludePreparation: true,
		Publication: &profile.PublicationRef{Tenant: "tenant-a", Id: "publication:sha256:" + strings.Repeat("b", 64)}}
	result, failure := client.InspectHttpTarget(context.Background(), input, profile.CallOptions{})
	if failure != nil || result.Value.CatalogTransaction != math.MaxUint64 || result.Value.Candidates[0].Reasons[0] != 777 || result.Metadata.Identity.OperationId != nil {
		test.Fatalf("exact read-only target fields changed: %v", failure)
	}
	for _, function := range []string{"foreign", "drift"} {
		input.Function = function
		_, failure = client.InspectHttpTarget(context.Background(), input, profile.CallOptions{})
		local, ok := failure.(*profile.ClientFailure)
		if !ok || local.Category != profile.FailureCategoryDecode || !local.Dispatched {
			test.Fatalf("unassociated target response accepted: %v", failure)
		}
	}
	input.Function = "future"
	result, failure = client.InspectHttpTarget(context.Background(), input, profile.CallOptions{})
	if failure != nil || result.Value.State != 777 || result.Value.Candidates[0].Preparation.State != 779 || result.Value.Candidates[0].Eligible {
		test.Fatal("future descriptive target states changed")
	}
	input.MaximumWaitMillis = 30001
	_, failure = client.InspectHttpTarget(context.Background(), input, profile.CallOptions{})
	local, ok := failure.(*profile.ClientFailure)
	if !ok || local.Category != profile.FailureCategoryInvalidRequest || local.Dispatched || peer.requests.Load() != 4 {
		test.Fatal("unbounded target inspection dispatched or retried")
	}
	if peer.accepted.Load() != 1 {
		test.Fatal("inspection opened additional physical channels")
	}
}
