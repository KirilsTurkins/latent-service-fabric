package transport

import (
	"context"
	"google.golang.org/protobuf/encoding/protowire"
	"google.golang.org/protobuf/reflect/protoreflect"
	"math"
	"unicode/utf8"
)

// Validate exact field ownership and collection limits before native allocation.
// The existing call ledger reserves the wire, native and owned DTO bytes together.
func validateTransactionWire(ctx context.Context, data []byte, descriptor protoreflect.MessageDescriptor, nodes *int, depth int) error {
	if depth > 16 || descriptor.Fields().Len() > 64 {
		return errBound
	}
	*nodes -= 1 + descriptor.Fields().Len()/8
	if *nodes < 0 {
		return errBound
	}
	singular := make(map[protowire.Number]bool)
	oneofs := make(map[protoreflect.FullName]bool)
	counts := make(map[protowire.Number]int)
	mapKeys := make(map[protowire.Number]map[string]bool)
	for len(data) != 0 {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		*nodes--
		if *nodes < 0 {
			return errBound
		}
		number, kind, consumed := protowire.ConsumeTag(data)
		if consumed < 0 || number < 1 || number > protowire.MaxValidNumber || kind == protowire.StartGroupType || kind == protowire.EndGroupType {
			return errShape
		}
		data = data[consumed:]
		length := protowire.ConsumeFieldValue(number, kind, data)
		if length < 0 {
			return errShape
		}
		field := descriptor.Fields().ByNumber(number)
		if field != nil {
			if !field.IsList() && !field.IsMap() {
				if singular[number] {
					return errShape
				}
				singular[number] = true
			}
			if group := field.ContainingOneof(); group != nil {
				if oneofs[group.FullName()] {
					return errShape
				}
				oneofs[group.FullName()] = true
			}
			if field.IsList() || field.IsMap() {
				counts[number]++
				maximum := 128
				if field.IsMap() {
					maximum = 32
				} else if field.Name() == "required_record_ids" {
					maximum = 256
				}
				if counts[number] > maximum {
					return errBound
				}
			}
			expected := protowire.VarintType
			if field.Kind() == protoreflect.StringKind || field.Kind() == protoreflect.BytesKind || field.Kind() == protoreflect.MessageKind {
				expected = protowire.BytesType
			}
			if kind != expected {
				return errShape
			}
			if kind == protowire.VarintType {
				value, size := protowire.ConsumeVarint(data)
				if size < 0 || field.Kind() == protoreflect.BoolKind && value > 1 || field.Kind() == protoreflect.Uint32Kind && value > math.MaxUint32 ||
					(field.Kind() == protoreflect.Int32Kind || field.Kind() == protoreflect.EnumKind) && (int64(value) < math.MinInt32 || int64(value) > math.MaxInt32) {
					return errShape
				}
			} else {
				content, size := protowire.ConsumeBytes(data)
				if size < 0 {
					return errShape
				}
				if field.Kind() == protoreflect.StringKind && !utf8.Valid(content) {
					return errShape
				}
				if field.Kind() == protoreflect.MessageKind {
					if failure := validateTransactionWire(ctx, content, field.Message(), nodes, depth+1); failure != nil {
						return failure
					}
					if field.IsMap() {
						key := transactionMapKey(content)
						if mapKeys[number] == nil {
							mapKeys[number] = make(map[string]bool)
						}
						if mapKeys[number][key] {
							return errShape
						}
						mapKeys[number][key] = true
					}
				}
			}
		}
		data = data[length:]
	}
	return nil
}

func transactionMapKey(data []byte) string {
	key := ""
	for len(data) != 0 {
		number, kind, consumed := protowire.ConsumeTag(data)
		data = data[consumed:]
		length := protowire.ConsumeFieldValue(number, kind, data)
		if number == 1 && kind == protowire.BytesType {
			value, _ := protowire.ConsumeBytes(data)
			key = string(value)
		}
		data = data[length:]
	}
	return key
}
