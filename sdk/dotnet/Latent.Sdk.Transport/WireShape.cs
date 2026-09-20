using Google.Protobuf.Reflection;

namespace Latent.Sdk.Transport;

internal static class WireShape
{
    internal static void Validate(ReadOnlySpan<byte> data, MessageDescriptor descriptor, GraphBudget budget, int depth = 0)
    {
        if (depth > 16) throw new GraphLimitException();
        var singular = new HashSet<int>();
        var oneofs = new HashSet<OneofDescriptor>();
        while (!data.IsEmpty)
        {
            budget.Spend();
            ulong tag = Varint(ref data);
            int number = checked((int)(tag >> 3));
            int wire = (int)(tag & 7);
            if (number is < 1 or > 536870911) throw new FormatException("invalid protobuf tag");
            FieldDescriptor? field = descriptor.FindFieldByNumber(number);
            if (field is not null)
            {
                if (!field.IsRepeated && !singular.Add(number)) throw new FormatException("duplicate singular protobuf field");
                if (field.ContainingOneof is not null && !oneofs.Add(field.ContainingOneof)) throw new FormatException("contradictory protobuf oneof");
                if (wire != Expected(field.FieldType) && !(Packed(field) && wire == 2)) throw new FormatException("incorrect protobuf wire type");
            }
            switch (wire)
            {
                case 0:
                    ulong value = Varint(ref data);
                    if (field?.FieldType == FieldType.UInt32 && value > uint.MaxValue ||
                        field?.FieldType == FieldType.Bool && value > 1 ||
                        field?.FieldType == FieldType.Enum && unchecked((long)value) is < int.MinValue or > int.MaxValue)
                        throw new FormatException("protobuf scalar overflow");
                    break;
                case 1: Take(ref data, 8); break;
                case 2:
                    ulong length = Varint(ref data);
                    if (length > (ulong)data.Length) throw new FormatException("truncated protobuf field");
                    ReadOnlySpan<byte> content = Take(ref data, (int)length);
                    if (field?.FieldType == FieldType.Message) Validate(content, field.MessageType, budget, depth + 1);
                    else if (field?.FieldType == FieldType.String) GraphBudget.Utf8.GetCharCount(content);
                    else if (field is not null && Packed(field))
                    {
                        while (!content.IsEmpty)
                        {
                            budget.Spend();
                            if (Expected(field.FieldType) == 1) Take(ref content, 8);
                            else if (Expected(field.FieldType) == 5) Take(ref content, 4);
                            else Varint(ref content);
                        }
                    }
                    break;
                case 5: Take(ref data, 4); break;
                default: throw new FormatException("unsupported protobuf group or wire type");
            }
        }
    }

    private static bool Packed(FieldDescriptor field) => field.IsRepeated && Expected(field.FieldType) != 2;

    private static int Expected(FieldType type) => type switch
    {
        FieldType.Double or FieldType.Fixed64 or FieldType.SFixed64 => 1,
        FieldType.String or FieldType.Bytes or FieldType.Message => 2,
        FieldType.Float or FieldType.Fixed32 or FieldType.SFixed32 => 5,
        _ => 0
    };

    private static ReadOnlySpan<byte> Take(ref ReadOnlySpan<byte> data, int length)
    {
        if (length > data.Length) throw new FormatException("truncated protobuf field");
        ReadOnlySpan<byte> result = data[..length];
        data = data[length..];
        return result;
    }

    private static ulong Varint(ref ReadOnlySpan<byte> data)
    {
        ulong value = 0;
        for (int shift = 0; shift <= 63; shift += 7)
        {
            if (data.IsEmpty) throw new FormatException("truncated protobuf varint");
            byte next = data[0];
            data = data[1..];
            if (shift == 63 && next > 1) throw new FormatException("protobuf varint overflow");
            value |= (ulong)(next & 127) << shift;
            if ((next & 128) == 0) return value;
        }
        throw new FormatException("unterminated protobuf varint");
    }
}
