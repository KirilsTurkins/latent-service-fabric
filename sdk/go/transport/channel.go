package transport

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/binary"
	"errors"
	"io"
	"net/http"
	"strconv"
	"strings"
	"sync/atomic"
	"time"

	"google.golang.org/protobuf/proto"
	"latent.dev/sdk/go/internal/rpc/controlv1"
	"latent.dev/sdk/go/profile"
)

type callKey struct{}

type callState struct {
	identity      profile.RequestIdentity
	metadata      profile.ResponseMetadata
	dispatched    bool
	requestLimit  int
	responseLimit int
	grpcStatus    *int32
	attempted     atomic.Bool
}

func (state *callState) fail(category profile.FailureCategory, message string) *profile.ClientFailure {
	outcome := state.metadata.Outcome
	if !state.dispatched {
		outcome = profile.OutcomeKnowledgeNotDispatched
	}
	return &profile.ClientFailure{
		Category: category, Message: message, GrpcStatus: state.grpcStatus,
		Dispatched: state.dispatched, Outcome: outcome, Identity: state.identity,
		AuditAck: state.metadata.AuditAck, AuditStatus: state.metadata.AuditStatus,
		AuditAttemptSequence: state.metadata.AuditAttemptSequence,
	}
}

type rpcChannel struct {
	client *Client
}

func (channel *rpcChannel) Invoke(ctx context.Context, method string, input, output proto.Message) error {
	state := ctx.Value(callKey{}).(*callState)
	if proto.Size(input) > state.requestLimit {
		return state.fail(profile.FailureCategoryLimit, "encoded request exceeds client limit")
	}
	payload, failure := proto.Marshal(input)
	if failure != nil {
		return state.fail(profile.FailureCategoryInvalidRequest, "request cannot be encoded")
	}
	packet := make([]byte, len(payload)+5)
	binary.BigEndian.PutUint32(packet[1:5], uint32(len(payload)))
	copy(packet[5:], payload)
	target := *channel.client.endpoint
	target.Path = method
	query, failure := http.NewRequestWithContext(ctx, http.MethodPost, target.String(), bytes.NewReader(packet))
	if failure != nil {
		return state.fail(profile.FailureCategoryInvalidRequest, "invalid RPC request")
	}
	deadline, _ := ctx.Deadline()
	remaining := time.Until(deadline)
	if remaining <= 0 || ctx.Err() != nil {
		return callContextFailure(ctx, state)
	}
	query.Header.Set("content-type", "application/grpc+proto")
	query.Header.Set("te", "trailers")
	query.Header.Set("grpc-accept-encoding", "identity")
	setTimeoutHeader(query)
	query.Header.Set("authorization", "Bearer "+channel.client.config.BearerToken)
	query.GetBody = nil
	reply, failure := channel.client.roundTrip(query)
	if failure != nil {
		return state.fail(profile.FailureCategoryTransport, "HTTP/2 request failed; outcome may be unknown")
	}
	defer reply.Body.Close()
	data, hasMessage, bodyFailure := readUnary(reply.Body, state.responseLimit)
	statusValues := headerValues(reply.Header, reply.Trailer, "grpc-status")
	if len(statusValues) == 1 {
		raw, parseFailure := strconv.ParseInt(statusValues[0], 10, 32)
		if parseFailure == nil && strconv.FormatInt(raw, 10) == statusValues[0] {
			status := int32(raw)
			state.grpcStatus = &status
		}
	}
	if failure = readAudit(reply.Header, reply.Trailer, state); failure != nil {
		return failure
	}
	if bodyFailure != nil {
		if errors.Is(bodyFailure, errBound) {
			return state.fail(profile.FailureCategoryLimit, "response exceeds client limit")
		}
		if errors.Is(bodyFailure, errShape) {
			return state.fail(profile.FailureCategoryDecode, "invalid unary response framing")
		}
		return state.fail(profile.FailureCategoryTransport, "incomplete unary response; outcome may be unknown")
	}
	contentTypes := reply.Header.Values("content-type")
	if reply.StatusCode != http.StatusOK || len(contentTypes) != 1 ||
		(contentTypes[0] != "application/grpc" && contentTypes[0] != "application/grpc+proto") ||
		len(statusValues) != 1 || state.grpcStatus == nil ||
		len(reply.Header.Values("content-encoding")) != 0 {
		return state.fail(profile.FailureCategoryDecode, "invalid RPC response headers")
	}
	encodings := headerValues(reply.Header, reply.Trailer, "grpc-encoding")
	if len(encodings) > 1 || (len(encodings) == 1 && encodings[0] != "identity") {
		return state.fail(profile.FailureCategoryDecode, "response compression is not supported")
	}
	if *state.grpcStatus != 0 {
		category := profile.FailureCategoryRpc
		if *state.grpcStatus == 4 {
			category = profile.FailureCategoryDeadline
		}
		result := state.fail(category, "remote RPC failed; recover by the original identity")
		if failure = channel.platformDetails(ctx, reply, result); failure != nil {
			return failure
		}
		return result
	}
	if !hasMessage {
		return state.fail(profile.FailureCategoryDecode, "unary response message is missing")
	}
	nodes := channel.client.config.MaxGraphNodes
	if failure = validateWire(ctx, data, output.ProtoReflect().Descriptor(), &nodes, 0); failure != nil {
		if errors.Is(failure, errBound) {
			return state.fail(profile.FailureCategoryLimit, "response graph exceeds client limit")
		}
		return state.fail(profile.FailureCategoryDecode, "invalid protobuf response")
	}
	if len(data)*3+(channel.client.config.MaxGraphNodes-nodes)*256 > channel.client.config.MaxGraphBytes {
		return state.fail(profile.FailureCategoryLimit, "decoded response allocation exceeds client limit")
	}
	if failure = (proto.UnmarshalOptions{RecursionLimit: 16}).Unmarshal(data, output); failure != nil {
		return state.fail(profile.FailureCategoryDecode, "invalid protobuf response")
	}
	return nil
}

func setTimeoutHeader(request *http.Request) {
	deadline, _ := request.Context().Deadline()
	remaining := max(time.Until(deadline), time.Nanosecond)
	request.Header.Set("grpc-timeout", strconv.FormatInt(int64((remaining+time.Millisecond-1)/time.Millisecond), 10)+"m")
}

func readUnary(body io.Reader, maximum int) ([]byte, bool, error) {
	var prefix [5]byte
	count, failure := io.ReadFull(body, prefix[:])
	if failure == io.EOF && count == 0 {
		return nil, false, nil
	}
	if failure != nil {
		return nil, false, failure
	}
	if prefix[0] != 0 {
		return nil, false, errShape
	}
	length := binary.BigEndian.Uint32(prefix[1:])
	if uint64(length) > uint64(maximum) {
		return nil, false, errBound
	}
	data := make([]byte, int(length))
	if _, failure = io.ReadFull(body, data); failure != nil {
		return nil, false, failure
	}
	var extra [1]byte
	if count, failure = io.ReadFull(body, extra[:]); count != 0 || failure != io.EOF {
		if failure != nil && failure != io.EOF {
			return nil, false, failure
		}
		return nil, false, errShape
	}
	return data, true, nil
}

func headerValues(header, trailer http.Header, name string) []string {
	return append(append([]string(nil), header.Values(name)...), trailer.Values(name)...)
}

func readAudit(header, trailer http.Header, state *callState) error {
	statuses := headerValues(header, trailer, "latent-audit-status")
	attempts := headerValues(header, trailer, "latent-audit-attempt")
	if len(statuses) > 1 || (len(statuses) == 1 && (len(statuses[0]) == 0 || len(statuses[0]) > 256)) || len(attempts) > 1 {
		return state.fail(profile.FailureCategoryDecode, "invalid audit response metadata")
	}
	if len(attempts) == 1 {
		sequence, valid := profile.ParseU64Decimal(attempts[0])
		if !valid {
			return state.fail(profile.FailureCategoryDecode, "invalid audit attempt sequence")
		}
		state.metadata.AuditAttemptSequence = &sequence
	}
	if len(statuses) == 0 {
		return nil
	}
	raw := statuses[0]
	state.metadata.AuditStatus = &raw
	var status profile.AuditAckStatus
	switch raw {
	case "durable":
		status = profile.AuditAckStatusDurable
	case "outcome-unknown":
		status = profile.AuditAckStatusOutcomeUnknown
	case "audit-unavailable":
		status = profile.AuditAckStatusAuditUnavailable
	case "disabled":
		status = profile.AuditAckStatusDisabled
	default:
		return nil
	}
	state.metadata.AuditAck = &profile.AuditAck{Status: status, AttemptSequence: state.metadata.AuditAttemptSequence}
	return nil
}

func (channel *rpcChannel) platformDetails(ctx context.Context, reply *http.Response, result *profile.ClientFailure) error {
	values := headerValues(reply.Header, reply.Trailer, "grpc-status-details-bin")
	if len(values) == 0 {
		return nil
	}
	if len(values) != 1 || len(values[0]) > 10924 {
		result.Category = profile.FailureCategoryDecode
		return result
	}
	data, failure := base64.StdEncoding.DecodeString(values[0])
	if failure != nil {
		data, failure = base64.RawStdEncoding.DecodeString(values[0])
	}
	wire := &controlv1.PlatformError{}
	maximumNodes := min(channel.client.config.MaxGraphNodes, 512)
	nodes := maximumNodes
	if failure != nil || len(data) > 8192 {
		result.Category = profile.FailureCategoryDecode
		return result
	}
	shapeFailure := validateWire(ctx, data, wire.ProtoReflect().Descriptor(), &nodes, 0)
	if errors.Is(shapeFailure, errBound) || len(data)*3+(maximumNodes-nodes)*256 > channel.client.config.MaxGraphBytes {
		result.Category = profile.FailureCategoryLimit
		result.Message = "remote diagnostic exceeds client graph limit"
		return result
	}
	if shapeFailure != nil || (proto.UnmarshalOptions{RecursionLimit: 16}).Unmarshal(data, wire) != nil || wire.Code == "" {
		result.Category = profile.FailureCategoryDecode
		return result
	}
	value := &profile.PlatformError{}
	if fromProto(wire, value) != nil {
		result.Category = profile.FailureCategoryDecode
		return result
	}
	value.Message = redact(value.Message, channel.client.config.BearerToken)
	for index := range value.DetailItems {
		for key, entry := range value.DetailItems[index].Fields {
			value.DetailItems[index].Fields[key] = redact(entry, channel.client.config.BearerToken)
		}
	}
	result.PlatformError = value
	return nil
}

func redact(value, token string) string {
	return strings.ReplaceAll(value, token, "[redacted]")
}

func callContextFailure(ctx context.Context, state *callState) *profile.ClientFailure {
	if errors.Is(ctx.Err(), context.Canceled) {
		return state.fail(profile.FailureCategoryLocalCancelled, "local wait cancelled; this does not cancel remote work")
	}
	return state.fail(profile.FailureCategoryDeadline, "local deadline expired; recover by the original identity")
}
