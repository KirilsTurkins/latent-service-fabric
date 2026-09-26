package transport

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"os"
	"reflect"
	"strconv"
	"testing"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protoreflect"
	"google.golang.org/protobuf/types/dynamicpb"
	"latent.dev/sdk/go/internal/rpc/controlv1"
	"latent.dev/sdk/go/internal/rpc/invocationv1"
	"latent.dev/sdk/go/profile"
)

func TestSharedWireVectors(test *testing.T) {
	data, failure := os.ReadFile("../../profile/fixtures.json")
	if failure != nil || len(data) > 128*1024 {
		test.Fatal("shared fixture input unavailable or oversized")
	}
	var fixtures struct {
		Cases []struct {
			Name          string          `json:"name"`
			Type          string          `json:"type"`
			Value         json.RawMessage `json:"value"`
			ResponseError string          `json:"response_error"`
		}
	}
	if failure := json.Unmarshal(data, &fixtures); failure != nil {
		test.Fatal(failure)
	}
	models := []any{
		profile.ResourceBudget{}, profile.ErrorDetail{}, profile.PlatformError{}, profile.ObjectMetadata{}, profile.PageRequest{}, profile.PageResponse{}, profile.AuditAck{},
		profile.InvocationTarget{}, profile.InvokeRequest{}, profile.BudgetConsumption{}, profile.Success{}, profile.DeclaredError{}, profile.InvokeResponse{},
		profile.CancelRequest{}, profile.CancelResponse{}, profile.GetActivationRequest{}, profile.ActivationSuccessSummary{}, profile.ActivationStatus{},
		profile.Policy{}, profile.ApplyPolicyRequest{}, profile.CapabilityPolicyOperation{}, profile.ApplyPolicyResponse{}, profile.GetPolicyRequest{}, profile.GetPolicyResponse{},
		profile.GetPolicyOperationRequest{}, profile.GetPolicyOperationResponse{}, profile.ListPoliciesRequest{}, profile.ListPoliciesResponse{},
		profile.CapabilityInspectionPolicy{}, profile.CapabilityBindingInspection{}, profile.CapabilityDescriptor{}, profile.ListCapabilitiesRequest{},
		profile.CapabilityInspectionRevision{}, profile.CapabilityResourceUsage{}, profile.ListCapabilitiesResponse{}, profile.CapabilityInspectionCeiling{},
	}
	descriptors := []protoreflect.FileDescriptor{
		controlv1.File_latent_control_v1_common_proto, controlv1.File_latent_control_v1_policy_proto,
		controlv1.File_latent_control_v1_capability_proto, invocationv1.File_latent_invocation_v1_invocation_proto,
	}
	covered := 0
	for _, fixture := range fixtures.Cases {
		var model reflect.Type
		for _, candidate := range models {
			if reflect.TypeOf(candidate).Name() == fixture.Type {
				model = reflect.TypeOf(candidate)
			}
		}
		if model == nil {
			continue
		}
		covered++
		test.Run(fixture.Name, func(test *testing.T) {
			var descriptor protoreflect.MessageDescriptor
			for _, file := range descriptors {
				if found := file.Messages().ByName(protoreflect.Name(fixture.Type)); found != nil {
					descriptor = found
					break
				}
			}
			if descriptor == nil {
				test.Fatal("profile vector lacks an authoritative protobuf descriptor")
			}
			source := reflect.New(model)
			if failure := fixtureDecode(fixture.Value, source.Elem()); failure != nil {
				test.Fatal(failure)
			}
			wire := dynamicpb.NewMessage(descriptor)
			failure := toProto(source.Interface(), wire)
			if fixture.ResponseError == "contradictory-oneof" {
				if !errors.Is(failure, errShape) {
					test.Fatal("contradictory shared oneof was silently selected")
				}
				return
			}
			if failure != nil {
				test.Fatal(failure)
			}
			encoded, failure := proto.Marshal(wire)
			if failure != nil {
				test.Fatal(failure)
			}
			nodes := 8192
			if validateWire(context.Background(), encoded, descriptor, &nodes, 0) != nil {
				test.Fatal("shared protobuf vector failed bounded decoding")
			}
			decoded := dynamicpb.NewMessage(descriptor)
			if proto.Unmarshal(encoded, decoded) != nil {
				test.Fatal("shared protobuf vector failed generated decoding")
			}
			target := reflect.New(model)
			if fromProto(decoded, target.Interface()) != nil || !profileEqual(source.Elem(), target.Elem()) {
				test.Fatalf("shared presence, raw bytes, enum, u64 or nested profile field changed for %s", fixture.Type)
			}
		})
	}
	if covered < 40 {
		test.Fatal("shared wire vector coverage unexpectedly shrank")
	}
	test.Logf("converted %d authoritative shared wire vectors; local-only facade vectors remain in profile tests", covered)
}

func fixtureDecode(data json.RawMessage, target reflect.Value) error {
	if target.Kind() == reflect.Pointer {
		target.Set(reflect.New(target.Type().Elem()))
		return fixtureDecode(data, target.Elem())
	}
	switch target.Kind() {
	case reflect.Struct:
		var fields map[string]json.RawMessage
		if failure := json.Unmarshal(data, &fields); failure != nil {
			return failure
		}
		for name, value := range fields {
			field := target.FieldByName(fieldName(protoreflect.Name(name)))
			if !field.IsValid() {
				return errShape
			}
			if failure := fixtureDecode(value, field); failure != nil {
				return failure
			}
		}
	case reflect.Map:
		var fields map[string]json.RawMessage
		if failure := json.Unmarshal(data, &fields); failure != nil {
			return failure
		}
		target.Set(reflect.MakeMapWithSize(target.Type(), len(fields)))
		for name, value := range fields {
			entry := reflect.New(target.Type().Elem()).Elem()
			if failure := fixtureDecode(value, entry); failure != nil {
				return failure
			}
			target.SetMapIndex(reflect.ValueOf(name), entry)
		}
	case reflect.Slice:
		if target.Type().Elem().Kind() == reflect.Uint8 {
			var encoded string
			if json.Unmarshal(data, &encoded) != nil {
				return errShape
			}
			value, failure := base64.StdEncoding.DecodeString(encoded)
			target.SetBytes(value)
			return failure
		}
		var values []json.RawMessage
		if failure := json.Unmarshal(data, &values); failure != nil {
			return failure
		}
		target.Set(reflect.MakeSlice(target.Type(), len(values), len(values)))
		for index, value := range values {
			if failure := fixtureDecode(value, target.Index(index)); failure != nil {
				return failure
			}
		}
	case reflect.String:
		var value string
		if failure := json.Unmarshal(data, &value); failure != nil {
			return failure
		}
		target.SetString(value)
	case reflect.Uint64:
		var decimal string
		if json.Unmarshal(data, &decimal) != nil {
			return errShape
		}
		value, valid := profile.ParseU64Decimal(decimal)
		if !valid {
			return errShape
		}
		target.SetUint(value)
	case reflect.Uint32:
		value, failure := strconv.ParseUint(string(data), 10, 32)
		if failure != nil {
			return failure
		}
		target.SetUint(value)
	case reflect.Int32:
		value, failure := strconv.ParseInt(string(data), 10, 32)
		if failure != nil {
			return failure
		}
		target.SetInt(value)
	case reflect.Bool:
		var value bool
		if failure := json.Unmarshal(data, &value); failure != nil {
			return failure
		}
		target.SetBool(value)
	default:
		return errShape
	}
	return nil
}

func profileEqual(left, right reflect.Value) bool {
	if left.Kind() == reflect.Pointer {
		if left.IsNil() || right.IsNil() {
			return left.IsNil() == right.IsNil()
		}
		return profileEqual(left.Elem(), right.Elem())
	}
	switch left.Kind() {
	case reflect.Struct:
		for index := 0; index < left.NumField(); index++ {
			if !profileEqual(left.Field(index), right.Field(index)) {
				return false
			}
		}
		return true
	case reflect.Map:
		if left.Len() != right.Len() {
			return false
		}
		iterator := left.MapRange()
		for iterator.Next() {
			value := right.MapIndex(iterator.Key())
			if !value.IsValid() || !profileEqual(iterator.Value(), value) {
				return false
			}
		}
		return true
	case reflect.Slice:
		if left.Len() != right.Len() {
			return false
		}
		if left.Type().Elem().Kind() == reflect.Uint8 {
			return bytes.Equal(left.Bytes(), right.Bytes())
		}
		for index := 0; index < left.Len(); index++ {
			if !profileEqual(left.Index(index), right.Index(index)) {
				return false
			}
		}
		return true
	default:
		return reflect.DeepEqual(left.Interface(), right.Interface())
	}
}
