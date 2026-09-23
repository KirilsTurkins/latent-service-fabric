using Lsf.Guest;

static class Checks
{
    static int tests;
    static void Require(bool value) { if (!value) throw new Exception("ownership assertion"); }
    static void Fails(Action action) {
        try { action(); } catch (InvalidOperationException) { return; }
        throw new Exception("misuse was accepted");
    }
    static void Case(Action action) { action(); tests++; }
    static void Main()
    {
        Case(() => {
            var drops = 0;
            var owner = new Owner<ulong, object>(0, value => { Require(value == 0); drops++; });
            var alias = owner;
            owner.Dispose(); alias.Dispose();
            Require(drops == 1);
            Fails(() => alias.Borrow(value => value));
            Fails(() => alias.Consume(value => value));
        });
        Case(() => {
            var calls = 0;
            var owner = new Owner<int, object>(7, _ => calls += 100);
            Fails(() => owner.Consume<int>(value => { Require(value == 7); calls++; throw new InvalidOperationException("uncertain"); }));
            owner.Dispose();
            Fails(() => owner.Consume(value => ++calls));
            Require(calls == 1);
        });
        Case(() => {
            var drops = 0;
            var owner = new Owner<int, object>(1, _ => drops++);
            Fails(() => owner.Borrow<int>(value => {
                Fails(() => owner.Borrow(v => v));
                Fails(() => owner.Consume(v => v));
                Fails(owner.Dispose);
                throw new InvalidOperationException("body");
            }));
            owner.Dispose(); Require(drops == 1);
        });
        Case(() => {
            var order = new List<int>();
            var scope = new Scope();
            for (var i = 0; i < 3; i++) scope.Own(new Owner<int, object>(i, value => {
                order.Add(value);
                if (value == 1) throw new InvalidOperationException("destructor");
            }));
            Fails(scope.Dispose); scope.Dispose();
            Require(order.SequenceEqual(new[] {2, 1, 0}));
        });
        Case(() => {
            var count = 0;
            var scope = new Scope();
            for (var i = 0; i < 256; i++) scope.Own(new Owner<int, object>(i, _ => count++));
            Fails(() => scope.Own(new Owner<int, object>(256, _ => count++)));
            scope.Dispose(); Require(count == 257);
        });
        Case(() => {
            var count = 0;
            var scope = new Scope(); scope.Dispose();
            Fails(() => scope.Own(new Owner<int, object>(1, _ => count++)));
            Require(count == 1);
        });
        Console.WriteLine($"C# ownership tests passed: {tests}");
    }
}
