using System.Collections;
using System.Reflection;
using System.Text;
using Google.Protobuf;
using Google.Protobuf.Reflection;

namespace Latent.Sdk.Transport;

internal sealed class GraphLimitException : Exception { }

internal sealed class GraphBudget
{
    internal static readonly UTF8Encoding Utf8 = new(false, true);
    private long bytes;
    private int nodes;
    private readonly CancellationToken cancellationToken;

    internal GraphBudget(long bytes, int nodes, CancellationToken cancellationToken)
    {
        this.bytes = bytes;
        this.nodes = nodes;
        this.cancellationToken = cancellationToken;
    }

    internal void Spend(long amount = 256)
    {
        cancellationToken.ThrowIfCancellationRequested();
        bytes -= amount;
        if (--nodes < 0 || bytes < 0) throw new GraphLimitException();
    }

    internal void Scan(object? value, int depth = 0)
    {
        Spend();
        if (depth > 16) throw new GraphLimitException();
        switch (value)
        {
            case null: return;
            case string text: Spend(4L * Utf8.GetByteCount(text)); return;
            case ReadOnlyMemory<byte> memory: Spend(3L * memory.Length); return;
            case IEnumerable sequence:
                foreach (object? item in sequence) Scan(item, depth + 1);
                return;
        }
        Type type = value.GetType();
        if (type.IsPrimitive || type.IsEnum) return;
        foreach (PropertyInfo property in type.GetProperties(BindingFlags.Public | BindingFlags.Instance))
            Scan(property.GetValue(value), depth + 1);
    }
}

internal static class ProfileCodec
{
    internal static string PropertyName(FieldDescriptor field) => char.ToUpperInvariant(field.JsonName[0]) + field.JsonName[1..];

    internal static IMessage ToWire(object value, IMessage message)
    {
        var selected = new HashSet<OneofDescriptor>();
        foreach (FieldDescriptor field in message.Descriptor.Fields.InFieldNumberOrder())
        {
            PropertyInfo property = value.GetType().GetProperty(PropertyName(field)) ?? throw new FormatException("profile field is missing");
            object? source = property.GetValue(value);
            if (source is null)
            {
                if (!field.HasPresence) throw new FormatException("nonoptional profile field is null");
                continue;
            }
            if (field.ContainingOneof is not null && !selected.Add(field.ContainingOneof))
                throw new FormatException("contradictory profile oneof");
            if (field.IsMap)
            {
                var destination = (IDictionary)field.Accessor.GetValue(message);
                FieldDescriptor key = field.MessageType.FindFieldByNumber(1);
                FieldDescriptor item = field.MessageType.FindFieldByNumber(2);
                foreach (object entry in (IEnumerable)source)
                {
                    Type pair = entry.GetType();
                    destination.Add(ToScalar(pair.GetProperty("Key")!.GetValue(entry)!, key),
                        ToScalar(pair.GetProperty("Value")!.GetValue(entry)!, item));
                }
            }
            else if (field.IsRepeated)
            {
                var destination = (IList)field.Accessor.GetValue(message);
                foreach (object item in (IEnumerable)source) destination.Add(ToScalar(item, field));
            }
            else field.Accessor.SetValue(message, ToScalar(source, field));
        }
        return message;
    }

    private static object ToScalar(object value, FieldDescriptor field) => value is null ? throw new FormatException("null protobuf value") : field.FieldType switch
    {
        FieldType.Message => ToWire(value, (IMessage)Activator.CreateInstance(field.MessageType.ClrType)!),
        FieldType.Bytes => ByteString.CopyFrom(((ReadOnlyMemory<byte>)value).Span),
        FieldType.Enum => Enum.ToObject(field.EnumType.ClrType, value.GetType().GetProperty("Value")!.GetValue(value)!),
        _ => value
    };

    internal static object FromWire(IMessage message, Type type)
    {
        ConstructorInfo constructor = type.GetConstructors().Single();
        ParameterInfo[] parameters = constructor.GetParameters();
        var fields = message.Descriptor.Fields.InFieldNumberOrder().ToDictionary(PropertyName);
        var arguments = new object?[parameters.Length];
        for (int index = 0; index < parameters.Length; index++)
        {
            ParameterInfo parameter = parameters[index];
            FieldDescriptor field = fields[parameter.Name!];
            if (field.HasPresence && !field.Accessor.HasValue(message)) continue;
            object source = field.Accessor.GetValue(message);
            if (field.IsMap)
            {
                Type[] types = parameter.ParameterType.GetGenericArguments();
                var destination = (IDictionary)Activator.CreateInstance(typeof(Dictionary<,>).MakeGenericType(types))!;
                FieldDescriptor item = field.MessageType.FindFieldByNumber(2);
                foreach (DictionaryEntry entry in (IDictionary)source) destination.Add(entry.Key, FromScalar(entry.Value!, item, types[1]));
                arguments[index] = destination;
            }
            else if (field.IsRepeated)
            {
                Type element = parameter.ParameterType.GetGenericArguments()[0];
                var destination = (IList)Activator.CreateInstance(typeof(List<>).MakeGenericType(element))!;
                foreach (object item in (IEnumerable)source) destination.Add(FromScalar(item, field, element));
                arguments[index] = destination;
            }
            else arguments[index] = FromScalar(source, field, Nullable.GetUnderlyingType(parameter.ParameterType) ?? parameter.ParameterType);
        }
        return constructor.Invoke(arguments);
    }

    private static object FromScalar(object value, FieldDescriptor field, Type type) => field.FieldType switch
    {
        FieldType.Message => FromWire((IMessage)value, type),
        FieldType.Bytes => new ReadOnlyMemory<byte>(((ByteString)value).ToByteArray()),
        FieldType.Enum => Activator.CreateInstance(type, Convert.ToInt32(value))!,
        _ => value
    };
}
