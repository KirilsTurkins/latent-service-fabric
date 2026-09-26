package transport

import (
	"context"

	"google.golang.org/protobuf/encoding/protowire"
	"google.golang.org/protobuf/reflect/protoreflect"
)

func validateWire(ctx context.Context, data []byte, descriptor protoreflect.MessageDescriptor, nodes *int, depth int) error {
	if depth > 16 {
		return errBound
	}
	oneofs := make(map[protoreflect.FullName]bool)
	for len(data) != 0 {
		if failure := ctx.Err(); failure != nil {
			return failure
		}
		*nodes--
		if *nodes < 0 {
			return errBound
		}
		number, kind, tagLength := protowire.ConsumeTag(data)
		if tagLength < 0 || number < 1 || kind == protowire.StartGroupType || kind == protowire.EndGroupType {
			return errShape
		}
		data = data[tagLength:]
		length := protowire.ConsumeFieldValue(number, kind, data)
		if length < 0 {
			return errShape
		}
		field := descriptor.Fields().ByNumber(number)
		if field != nil {
			if group := field.ContainingOneof(); group != nil && !group.IsSynthetic() {
				if oneofs[group.FullName()] {
					return errShape
				}
				oneofs[group.FullName()] = true
			}
			expected := protowire.VarintType
			if field.Kind() == protoreflect.StringKind || field.Kind() == protoreflect.BytesKind || field.Kind() == protoreflect.MessageKind {
				expected = protowire.BytesType
			}
			if kind != expected {
				return errShape
			}
			if field.Kind() == protoreflect.MessageKind {
				nested, consumed := protowire.ConsumeBytes(data)
				if consumed < 0 {
					return errShape
				}
				if failure := validateWire(ctx, nested, field.Message(), nodes, depth+1); failure != nil {
					return failure
				}
			}
		}
		data = data[length:]
	}
	return nil
}
