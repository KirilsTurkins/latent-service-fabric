package transport

import (
	"context"
	"encoding/base64"
	"net/http"
	"strconv"
	"strings"
	"testing"

	"google.golang.org/protobuf/proto"
	"latent.dev/sdk/go/internal/rpc/controlv1"
	"latent.dev/sdk/go/profile"
)

func TestGraphBudgetsCoverRequestsResponsesAndDiagnostics(test *testing.T) {
	test.Run("request-before-dispatch", func(test *testing.T) {
		peer := newPeer(test, func(writer http.ResponseWriter, request *http.Request) {
			test.Error("oversized request graph reached the wire")
		})
		client := testClient(test, peer, func(config *Config) { config.MaxGraphBytes = 1024 })
		request := invokeRequest("graph-a")
		request.Payload = make([]byte, 2048)
		_, failure := client.Invoke(context.Background(), request, profile.CallOptions{})
		assertFailure(test, failure, profile.FailureCategoryLimit, false)
		if peer.requests.Load() != 0 {
			test.Fatal("request allocation bound did not prevent dispatch")
		}
	})
	for _, kind := range []string{"response-bytes", "response-nodes", "error-detail"} {
		test.Run(kind, func(test *testing.T) {
			peer := newPeer(test, func(writer http.ResponseWriter, request *http.Request) {
				if kind == "error-detail" {
					detail, failure := proto.Marshal(&controlv1.PlatformError{Code: "state-conflict", Message: strings.Repeat("x", 1024)})
					if failure != nil {
						test.Error(failure)
					}
					writer.Header().Set("grpc-status-details-bin", base64.RawStdEncoding.EncodeToString(detail))
					writer.Header().Set("latent-audit-status", "future-state")
					writer.Header().Set("latent-audit-attempt", "18446744073709551615")
					peerFailure(writer, "9")
					return
				}
				policy := &controlv1.Policy{Id: "policy-a", Document: strings.Repeat("x", 1024)}
				if kind == "response-nodes" {
					policy.Metadata = &controlv1.ObjectMetadata{Labels: make(map[string]string)}
					for index := 0; index < 40; index++ {
						policy.Metadata.Labels[strconv.Itoa(index)] = "x"
					}
				}
				peerReply(writer, &controlv1.GetPolicyResponse{Policy: policy})
			})
			client := testClient(test, peer, func(config *Config) {
				if kind == "response-nodes" {
					config.MaxGraphNodes = 32
				} else {
					config.MaxGraphBytes = 1024
				}
			})
			_, failure := client.GetPolicy(context.Background(), profile.GetPolicyRequest{Id: "policy-a", RecordKind: profile.CapabilityPolicyRecordKindPolicy}, profile.CallOptions{})
			detail := assertFailure(test, failure, profile.FailureCategoryLimit, true)
			if kind == "error-detail" && (detail.GrpcStatus == nil || *detail.GrpcStatus != 9 || detail.AuditAck != nil ||
				detail.AuditStatus == nil || *detail.AuditStatus != "future-state" || detail.AuditAttemptSequence == nil || *detail.AuditAttemptSequence != ^uint64(0)) {
				test.Fatal("bounded partial diagnostic decoding lost independent RPC/audit facts")
			}
		})
	}
}
