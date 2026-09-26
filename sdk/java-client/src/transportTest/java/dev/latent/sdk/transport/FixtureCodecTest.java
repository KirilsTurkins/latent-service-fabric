package dev.latent.sdk.transport;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.google.protobuf.Message;
import dev.latent.sdk.Management;
import java.lang.reflect.ParameterizedType;
import java.lang.reflect.Type;
import java.nio.ByteBuffer;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

final class FixtureCodecTest {
    private FixtureCodecTest() { }

    static Object value(Type type, JsonElement json) throws Exception {
        boolean absent = json == null || json.isJsonNull();
        if (type instanceof ParameterizedType parameterized) {
            Type[] arguments = parameterized.getActualTypeArguments();
            if (parameterized.getRawType() == Optional.class) return absent ? Optional.empty() : Optional.of(value(arguments[0], json));
            if (parameterized.getRawType() == List.class) {
                var result = new ArrayList<>();
                if (!absent) for (var item : json.getAsJsonArray()) result.add(value(arguments[0], item));
                return List.copyOf(result);
            }
            if (parameterized.getRawType() == Map.class) {
                var result = new LinkedHashMap<>();
                if (!absent) for (var entry : json.getAsJsonObject().entrySet()) result.put(entry.getKey(), value(arguments[1], entry.getValue()));
                return Map.copyOf(result);
            }
        }
        Class<?> kind = (Class<?>) type;
        if (kind == String.class) return absent ? "" : json.getAsString();
        if (kind == long.class || kind == Long.class) return absent ? 0L : Long.parseUnsignedLong(json.getAsString());
        if (kind == int.class || kind == Integer.class) return absent ? 0 : json.getAsInt();
        if (kind == boolean.class || kind == Boolean.class) return !absent && json.getAsBoolean();
        if (kind == ByteBuffer.class) return ByteBuffer.wrap(absent ? new byte[0] : Base64.getDecoder().decode(json.getAsString())).asReadOnlyBuffer();
        var fields = kind.getRecordComponents();
        if (fields.length == 1 && fields[0].getName().equals("value")) return kind.getConstructor(int.class).newInstance(absent ? 0 : json.getAsInt());
        JsonObject object = absent ? new JsonObject() : json.getAsJsonObject();
        Object[] values = new Object[fields.length];
        Class<?>[] parameters = new Class<?>[fields.length];
        for (int index = 0; index < fields.length; index++) {
            var field = fields[index];
            String name = field.getName().replaceAll("([A-Z])", "_$1").toLowerCase(java.util.Locale.ROOT);
            values[index] = value(field.getGenericType(), object.get(name));
            parameters[index] = field.getType();
        }
        return kind.getConstructor(parameters).newInstance(values);
    }

    static void run() throws Exception {
        Path path = Path.of("sdk/profile/fixtures.json");
        if (Files.size(path) > 1048576) throw new AssertionError("fixture bound");
        var cases = JsonParser.parseString(Files.readString(path)).getAsJsonObject().getAsJsonArray("cases");
        int count = 0;
        int rejected = 0;
        for (var entry : cases) {
            var test = entry.getAsJsonObject();
            Class<?> kind = Class.forName("dev.latent.sdk.Management$" + test.get("type").getAsString());
            java.lang.reflect.Method encode;
            try { encode = Wire.class.getMethod("toWire", kind); }
            catch (NoSuchMethodException excluded) { continue; }
            Object model = value(kind, test.get("value"));
            try {
                Message wire = (Message) encode.invoke(null, model);
                Message decoded = wire.getParserForType().parseFrom(wire.toByteArray());
                Object actual = Wire.class.getMethod("fromWire", encode.getReturnType()).invoke(null, decoded);
                if (!model.equals(actual)) throw new AssertionError("shared protobuf vector " + test.get("name"));
                count++;
            } catch (java.lang.reflect.InvocationTargetException failure) {
                if (!test.has("response_error") || !test.get("response_error").getAsString().equals("contradictory-oneof")
                        || !(failure.getCause() instanceof IllegalArgumentException)) throw failure;
                rejected++;
            }
        }
        if (count != 50 || rejected != 1) throw new AssertionError("incomplete shared protobuf cases " + count + "/" + rejected);
        System.out.println("Java shared protobuf cases: " + count + "; contradictory oneof rejected: " + rejected);
    }
}
