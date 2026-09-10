"""Check retained public results against the fixed fixture and SHA selection."""
from tools.optimization_evidence.common import canonical, fields, require, sha256, uint
from . import fixtures


def error(case):
    require(case in ("route-miss", "export-miss"), "catalog-oracle-error-case")
    code, reason = (("RouteUnavailable", "route-not-found") if case == "route-miss"
                    else ("IncompatibleContract", "contract-or-function-not-exported"))
    return {"code": code, "message": reason, "retryable": False,
            "details": [{"kind": "deployment-catalog", "fields": {"reason": reason}}]}


class Oracle:
    def __init__(self, fixture, count, shape, generation, *, updated=False):
        require(type(count) is int and 1 <= count <= 100000 and shape in ("distinct", "shared")
                and type(generation) is int and generation > 0 and type(updated) is bool,
                "catalog-oracle-population")
        self.fixture, self.count, self.shape = fixture, count, shape
        self.generation, self.updated = generation, updated
        self.ordered = fixture.ordered_revisions(count, shape, updated=updated) if shape == "shared" else None

    def outcome(self, case, sample):
        index, target, key = fixtures.input_case(self.count, case, sample, self.shape)
        if case in ("route-miss", "export-miss"):
            return {"error": error(case)}
        selected = self.fixture.selected(self.ordered, target, key) if self.shape == "shared" and target["route"] is None else index
        weight = 2 if self.updated and selected == 0 else 1
        attributes = self.fixture.attributes(selected, self.shape, weight)
        return {"result": {"revision": self.fixture.revision(selected, self.shape),
                           "release": self.fixture.release(selected), "generation": str(self.generation),
                           "attributes_digest": sha256(canonical(attributes))}}

    def check(self, row, case, sample, *, extra=""):
        expected = self.outcome(case, sample)
        fields(row, extra + " " + next(iter(expected)))
        require(all(row[key] == value for key, value in expected.items()), "catalog-public-result-oracle")
        if "index" in row:
            index, _, _ = fixtures.input_case(self.count, case, sample, self.shape)
            require(uint(row["index"]) == index, "catalog-public-result-index")
        return "error" not in expected


class Operations:
    def __init__(self):
        self.commands = 0
        self.values = {key: {"attempted": 0, "returned_ok": 0, "returned_error": 0}
                       for key in ("publications", "applies", "resolves", "pins", "policies")}

    def add(self, operation, succeeded=True, count=1, *, ordinal=None):
        require(operation in self.values and type(count) is int and count > 0 and type(succeeded) is bool,
                "catalog-operation-count")
        if ordinal is not None:
            require(uint(ordinal) == self.commands + 1, "catalog-command-lineage")
        self.commands += count
        self.values[operation]["attempted"] += count
        self.values[operation]["returned_ok" if succeeded else "returned_error"] += count

    def snapshot(self):
        return {name: {key: str(value) for key, value in row.items()} for name, row in self.values.items()}

    def complete(self, observed, expected):
        require(observed == self.snapshot(), "catalog-operation-result-counts")
        require(self.commands == expected["commands"]
                and all(row["attempted"] == expected[name] for name, row in self.values.items()),
                "catalog-operation-population")
