"""Fixed public receipts and weighted selections across delete/recreation."""
from tools.optimization_backend_revision.catalog.oracle import error
from tools.optimization_evidence.common import canonical, fields, require, sha256, uint
from . import fixtures, model

STATES = {"seed": 1, "unchanged-apply": 2, "weight-update": 3, "delete": 4, "reapply": 5}
KEY = "catalog-key-00000"


def decimals(value):
    if type(value) is int:
        return str(value)
    if isinstance(value, dict):
        return {key: decimals(item) for key, item in value.items()}
    if isinstance(value, list):
        return [decimals(item) for item in value]
    return value


class Oracle:
    def __init__(self, fixture, count, shape):
        require(type(count) is int and count in (4, 8, 100, 1000, 10000) and shape in model.SHAPES,
                "catalog-mutation-oracle-population")
        self.fixture, self.count, self.shape = fixture, count, shape
        self.ordered = sorted((fixture.revision(index, shape), index) for index in range(count)) if shape == "shared" else []

    def target(self, route):
        require(route in ("named", "default"), "catalog-mutation-proof-route")
        return {"tenant": fixtures.TENANT, "service": fixtures.service(0, self.shape),
                "contract": fixtures.CONTRACT, "function": "echo",
                "route": fixtures.name(0) if route == "named" else None}

    def projection(self, index, weight, generation):
        deployment = self.fixture.deployment(index, self.shape, weight)
        return {"id": fixtures.name(index), "tenant": fixtures.TENANT,
                "service": fixtures.service(index, self.shape), "release": self.fixture.release(index),
                "weight": str(weight), "object_generation": str(generation),
                "manifest_digest": sha256(canonical(deployment))}

    def get(self, state):
        require(state in STATES, "catalog-mutation-oracle-state")
        return {"result": None if state == "delete" else self.projection(0, 2 if state == "weight-update" else 1, STATES[state])}

    def mutation(self, state):
        require(state in model.MUTATIONS, "catalog-mutation-oracle-mutation")
        if state == "delete":
            return {"result": {"deleted": self.projection(0, 2, 3), "catalog_generation": "4"}}
        return {"result": {"deployment": self.get(state)["result"], "catalog_generation": str(STATES[state])}}

    def resolved(self, state, route):
        require(state in STATES, "catalog-mutation-oracle-state")
        target = self.target(route)
        if state == "delete" and (route == "named" or self.shape == "distinct"):
            return {"error": error("route-miss")}
        index = 0
        if route == "default" and self.shape == "shared":
            rows, ends, total = [], [], 0
            for revision, current in self.ordered:
                if state == "delete" and current == 0:
                    continue
                total += 2 if state == "weight-update" and current == 0 else 1
                rows.append((revision, current))
                ends.append(total)
            index = self.fixture.selected((rows, ends), target, KEY)
        weight = 2 if state == "weight-update" and index == 0 else 1
        return {"result": {"revision": self.fixture.revision(index, self.shape),
                "release": self.fixture.release(index), "generation": str(STATES[state]),
                "attributes_digest": sha256(canonical(self.fixture.attributes(index, self.shape, weight)))}}

    def policy(self):
        template = self.fixture.template()
        return {"result": decimals({"deployment_ceiling": template["deployment"]["spec"]["resources"],
                "execution": template["capsule"]["execution"],
                "placement": template["deployment"]["spec"]["placement"]})}


class Operations:
    def __init__(self):
        self.commands = 0
        self.values = {key: {"attempted": 0, "returned_ok": 0, "returned_error": 0}
                       for key in model.OPERATION_KEYS}

    def add(self, operation, succeeded=True, count=1, *, ordinal=None):
        require(operation in self.values and type(count) is int and count > 0 and type(succeeded) is bool,
                "catalog-mutation-operation-count")
        if ordinal is not None:
            require(uint(ordinal) == self.commands + 1, "catalog-mutation-command-lineage")
        self.commands += count
        self.values[operation]["attempted"] += count
        self.values[operation]["returned_ok" if succeeded else "returned_error"] += count

    def snapshot(self):
        return {name: {key: str(value) for key, value in row.items()} for name, row in self.values.items()}

    def complete(self, observed, expected):
        fields(observed, " ".join(self.values))
        require(observed == self.snapshot(), "catalog-mutation-operation-result-counts")
        require(self.commands == expected["commands"]
                and all(row["attempted"] == expected[name] for name, row in self.values.items()),
                "catalog-mutation-operation-population")
