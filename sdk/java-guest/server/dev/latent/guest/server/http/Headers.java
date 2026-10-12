package dev.latent.guest.server.http;

import java.util.AbstractMap;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/** Bounded case-insensitive HTTP fields, retaining repeated value order. */
public final class Headers extends AbstractMap<String, List<String>> {
    private final Map<String, List<String>> values = new LinkedHashMap<>();
    private boolean frozen;

    static String name(Object value) {
        if (!(value instanceof String)) throw new IllegalArgumentException("invalid header name");
        String name = ((String) value).toLowerCase(Locale.ROOT);
        if (name.isEmpty() || name.length() > 64) throw new IllegalArgumentException("invalid header name");
        for (int i = 0; i < name.length(); i++) {
            char c = name.charAt(i);
            if (!(c >= 'a' && c <= 'z' || c >= '0' && c <= '9' || "!#$%&'*+-.^_`|~".indexOf(c) >= 0)) {
                throw new IllegalArgumentException("invalid header name");
            }
        }
        return name;
    }

    static String field(String value) {
        if (value == null || value.length() > 4096 || !value.isEmpty()
                && (value.charAt(0) == ' ' || value.charAt(value.length() - 1) == ' ')) {
            throw new IllegalArgumentException("invalid header value");
        }
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            if (c < 32 || c == 127 || c > 255) throw new IllegalArgumentException("invalid header value");
        }
        return value;
    }

    private void mutable() {
        if (frozen) throw new IllegalStateException("headers are sealed");
    }

    @Override public List<String> put(String key, List<String> value) {
        mutable();
        String selected = name(key);
        if (value == null || value.size() > 64) throw new IllegalArgumentException("header value limit");
        ArrayList<String> copy = new ArrayList<>();
        for (String item : value) copy.add(field(item));
        List<String> old = values.put(selected, Collections.unmodifiableList(copy));
        try { check(); }
        catch (RuntimeException failure) {
            if (old == null) values.remove(selected); else values.put(selected, old);
            throw failure;
        }
        return old;
    }

    @Override public List<String> get(Object key) { return values.get(name(key)); }
    @Override public boolean containsKey(Object key) { return values.containsKey(name(key)); }
    @Override public List<String> remove(Object key) { mutable(); return values.remove(name(key)); }
    @Override public void clear() { mutable(); values.clear(); }
    @Override public Set<Entry<String, List<String>>> entrySet() { return Collections.unmodifiableMap(values).entrySet(); }
    public String getFirst(String key) {
        List<String> fields = get(key);
        return fields == null || fields.isEmpty() ? null : fields.get(0);
    }
    public void add(String key, String value) {
        List<String> old = get(key);
        ArrayList<String> combined = new ArrayList<>(old == null ? Collections.emptyList() : old);
        combined.add(field(value));
        put(key, combined);
    }
    public void set(String key, String value) { put(key, Collections.singletonList(field(value))); }
    public void freeze() { check(); frozen = true; }
    public boolean sealed() { return frozen; }
    public void check() {
        int count = 0, bytes = 0;
        for (Entry<String, List<String>> entry : values.entrySet()) {
            for (String value : entry.getValue()) {
                count++;
                bytes += entry.getKey().length() + field(value).length();
            }
        }
        if (count > 64 || bytes > 16384) throw new IllegalArgumentException("header aggregate limit");
    }
}
