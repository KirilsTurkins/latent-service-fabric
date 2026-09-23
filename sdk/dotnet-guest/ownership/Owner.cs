using System;
using System.Collections.Generic;

namespace Lsf.Guest;

/// <summary>Aliases share one live/borrowed/consumed state. No finalizer or retry.</summary>
public sealed class Owner<T, TKind> : IDisposable
{
    private T value;
    private readonly Action<T> release;
    private bool live = true;
    private bool borrowed;
    internal Owner(T value, Action<T> release) { this.value = value; this.release = release; }
    public bool IsOpen => live;
    internal R Borrow<R>(Func<T, R> operation)
    {
        if (!live || borrowed) throw new InvalidOperationException("owner is closed or borrowed");
        borrowed = true;
        try { return operation(value); }
        finally { borrowed = false; }
    }
    internal R Consume<R>(Func<T, R> operation)
    {
        if (!live || borrowed) throw new InvalidOperationException("owner is closed or borrowed");
        live = false;
        var moved = value;
        value = default!;
        return operation(moved);
    }
    public void Dispose()
    {
        if (!live) return;
        Consume(value => { release(value); return true; });
    }
}

/// <summary>Finite reverse-order cleanup, attempting every owner even on failure.</summary>
public sealed class Scope : IDisposable
{
    private readonly List<IDisposable> owners = new();
    private bool live = true;
    public T Own<T>(T owner) where T : IDisposable
    {
        if (!live || owners.Count >= 256) {
            owner.Dispose();
            throw new InvalidOperationException("scope is closed or full");
        }
        owners.Add(owner);
        return owner;
    }
    public void Dispose()
    {
        if (!live) return;
        live = false;
        Exception? failure = null;
        for (int index = owners.Count - 1; index >= 0; --index) {
            try { owners[index].Dispose(); }
            catch (Exception error) { failure ??= error; }
        }
        owners.Clear();
        if (failure is not null) throw new InvalidOperationException("scope cleanup failed", failure);
    }
}
