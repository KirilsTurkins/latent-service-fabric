package transport

import (
	"bytes"
	"errors"
	"reflect"
	"strings"

	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/reflect/protoreflect"
)

var errShape = errors.New("invalid protobuf profile shape")
var errBound = errors.New("protobuf profile exceeds client limits")

func fieldName(name protoreflect.Name) string {
	parts := strings.Split(string(name), "_")
	for index, part := range parts {
		parts[index] = strings.ToUpper(part[:1]) + part[1:]
	}
	return strings.Join(parts, "")
}

func toProto(source any, target proto.Message) error {
	return writeMessage(reflect.ValueOf(source), target.ProtoReflect())
}

func writeMessage(source reflect.Value, target protoreflect.Message) error {
	if source.Kind() == reflect.Pointer {
		source = source.Elem()
	}
	fields := target.Descriptor().Fields()
	for index := 0; index < fields.Len(); index++ {
		field := fields.Get(index)
		value := source.FieldByName(fieldName(field.Name()))
		if !value.IsValid() {
			return errShape
		}
		if value.Kind() == reflect.Pointer {
			if value.IsNil() {
				continue
			}
			value = value.Elem()
		}
		if group := field.ContainingOneof(); group != nil && target.WhichOneof(group) != nil {
			return errShape
		}
		switch {
		case field.IsMap():
			mapping := target.Mutable(field).Map()
			iterator := value.MapRange()
			for iterator.Next() {
				entry, failure := writeScalar(iterator.Value(), field.MapValue(), mapping.NewValue())
				if failure != nil {
					return failure
				}
				mapping.Set(protoreflect.ValueOfString(iterator.Key().String()).MapKey(), entry)
			}
		case field.IsList():
			list := target.Mutable(field).List()
			for item := 0; item < value.Len(); item++ {
				entry, failure := writeScalar(value.Index(item), field, list.NewElement())
				if failure != nil {
					return failure
				}
				list.Append(entry)
			}
		default:
			entry, failure := writeScalar(value, field, target.NewField(field))
			if failure != nil {
				return failure
			}
			target.Set(field, entry)
		}
	}
	return nil
}

func writeScalar(source reflect.Value, field protoreflect.FieldDescriptor, target protoreflect.Value) (protoreflect.Value, error) {
	switch field.Kind() {
	case protoreflect.MessageKind:
		failure := writeMessage(source, target.Message())
		return target, failure
	case protoreflect.StringKind:
		return protoreflect.ValueOfString(source.String()), nil
	case protoreflect.BytesKind:
		return protoreflect.ValueOfBytes(bytes.Clone(source.Bytes())), nil
	case protoreflect.BoolKind:
		return protoreflect.ValueOfBool(source.Bool()), nil
	case protoreflect.Uint64Kind:
		return protoreflect.ValueOfUint64(source.Uint()), nil
	case protoreflect.Uint32Kind:
		return protoreflect.ValueOfUint32(uint32(source.Uint())), nil
	case protoreflect.EnumKind:
		return protoreflect.ValueOfEnum(protoreflect.EnumNumber(source.Int())), nil
	default:
		return protoreflect.Value{}, errShape
	}
}

func fromProto(source proto.Message, target any) error {
	return readMessage(source.ProtoReflect(), reflect.ValueOf(target).Elem())
}

func readMessage(source protoreflect.Message, target reflect.Value) error {
	fields := source.Descriptor().Fields()
	for index := 0; index < fields.Len(); index++ {
		field := fields.Get(index)
		if !source.Has(field) {
			continue
		}
		value := source.Get(field)
		destination := target.FieldByName(fieldName(field.Name()))
		if !destination.IsValid() {
			return errShape
		}
		if destination.Kind() == reflect.Pointer {
			destination.Set(reflect.New(destination.Type().Elem()))
			destination = destination.Elem()
		}
		switch {
		case field.IsMap():
			destination.Set(reflect.MakeMapWithSize(destination.Type(), value.Map().Len()))
			var failure error
			value.Map().Range(func(key protoreflect.MapKey, entry protoreflect.Value) bool {
				converted := reflect.New(destination.Type().Elem()).Elem()
				failure = readScalar(entry, field.MapValue(), converted)
				if failure == nil {
					destination.SetMapIndex(reflect.ValueOf(key.String()), converted)
				}
				return failure == nil
			})
			if failure != nil {
				return failure
			}
		case field.IsList():
			list := value.List()
			destination.Set(reflect.MakeSlice(destination.Type(), list.Len(), list.Len()))
			for item := 0; item < list.Len(); item++ {
				if failure := readScalar(list.Get(item), field, destination.Index(item)); failure != nil {
					return failure
				}
			}
		default:
			if failure := readScalar(value, field, destination); failure != nil {
				return failure
			}
		}
	}
	return nil
}

func readScalar(source protoreflect.Value, field protoreflect.FieldDescriptor, target reflect.Value) error {
	switch field.Kind() {
	case protoreflect.MessageKind:
		return readMessage(source.Message(), target)
	case protoreflect.StringKind:
		target.SetString(source.String())
	case protoreflect.BytesKind:
		target.SetBytes(bytes.Clone(source.Bytes()))
	case protoreflect.BoolKind:
		target.SetBool(source.Bool())
	case protoreflect.Uint64Kind, protoreflect.Uint32Kind:
		target.SetUint(source.Uint())
	case protoreflect.EnumKind:
		target.SetInt(int64(source.Enum()))
	default:
		return errShape
	}
	return nil
}

type graphBudget struct {
	bytes int
	nodes int
}

func (budget *graphBudget) scan(value reflect.Value, depth int) error {
	if depth > 16 || budget.nodes <= 0 || int64(value.Type().Size()) > int64(budget.bytes) {
		return errBound
	}
	budget.nodes--
	budget.bytes -= int(value.Type().Size())
	switch value.Kind() {
	case reflect.Pointer:
		if !value.IsNil() {
			return budget.scan(value.Elem(), depth+1)
		}
	case reflect.Struct:
		for index := 0; index < value.NumField(); index++ {
			if failure := budget.scan(value.Field(index), depth+1); failure != nil {
				return failure
			}
		}
	case reflect.String:
		budget.bytes -= value.Len()
	case reflect.Slice:
		if value.Type().Elem().Kind() == reflect.Uint8 {
			budget.bytes -= value.Len()
			break
		}
		if value.Len() > budget.nodes {
			return errBound
		}
		for index := 0; index < value.Len(); index++ {
			if failure := budget.scan(value.Index(index), depth+1); failure != nil {
				return failure
			}
		}
	case reflect.Map:
		if value.Len() > budget.nodes/2 || value.Len() > budget.bytes/64 {
			return errBound
		}
		budget.bytes -= 64 * value.Len()
		iterator := value.MapRange()
		for iterator.Next() {
			if failure := budget.scan(iterator.Key(), depth+1); failure != nil {
				return failure
			}
			if failure := budget.scan(iterator.Value(), depth+1); failure != nil {
				return failure
			}
		}
	}
	if budget.bytes < 0 {
		return errBound
	}
	return nil
}
