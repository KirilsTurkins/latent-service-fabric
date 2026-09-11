"""Close the exact setup, polling, background and progress schedule after replay."""
from __future__ import annotations

from collections import defaultdict
from pathlib import PurePosixPath

from tools.optimization_docker.client_evidence import _read
from tools.optimization_docker.owned import encoded
from tools.optimization_evidence.common import canonical, decode, fields, integer, require, uint
from . import model, services, transport_evidence as transport

MAX_PROGRESS_BYTES = 32 * 1024**2


def _same(actual, expected, reason):
    require(canonical(actual) == canonical(expected), reason)


def _progress(path, expected, lower, upper):
    original = _read(path, MAX_PROGRESS_BYTES)
    rows = original.splitlines(keepends=True)
    require(len(rows) == len(expected) <= 20_000, "kubernetes-closure-progress-population")
    previous = lower
    for ordinal, (line, (kind, value, begin, end)) in enumerate(zip(rows, expected)):
        require(line.endswith(b"\n"), "kubernetes-closure-progress-framing")
        row = fields(decode(line, MAX_PROGRESS_BYTES), "ordinal kind observed_nanos value")
        require(encoded(row) == line and integer(row["ordinal"]) == ordinal,
                "kubernetes-closure-progress-original")
        _same([row["kind"], row["value"]], [kind, value], "kubernetes-closure-progress-event")
        observed = uint(row["observed_nanos"])
        require(max(previous, begin, lower) <= observed <= min(end, upper),
                "kubernetes-closure-progress-clock")
        previous = observed


class Closure:
    def __init__(self, suite, root, journal, bootstrap, used):
        self.suite, self.root, self.journal, self.bootstrap, self.used = suite, root, journal, bootstrap, used
        self.lower, self.upper = uint(suite["started_nanos"]), uint(suite["finished_nanos"])
        self.base = "/api/v1/namespaces/" + suite["namespace"]
        self.remote = model.host_path(suite["owner"], suite["run_id"])
        self.polls = defaultdict(list)
        for ordinal, call in enumerate(journal["rows"]):
            raw = call["raw"]
            if raw["provider"] == "kubernetes" and raw["method"] == "GET":
                self.polls[raw["path"]].append(ordinal)
        require(isinstance(used, set) and all(type(index) is int and 0 <= index < len(journal["rows"])
                                           for index in used), "kubernetes-closure-used-set")

    def call(self, ordinal, *, consume=True, **expected):
        selected = transport.get(self.journal, ordinal, **expected)
        if consume:
            require(ordinal not in self.used, "kubernetes-closure-call-already-used")
            self.used.add(ordinal)
        return selected

    def time(self, ordinal, endpoint="finished_nanos"):
        return uint(self.journal["rows"][integer(ordinal, 0, len(self.journal["rows"]) - 1)][endpoint])

    def preparation_order(self):
        expected = ["fixtures", "tools"]
        for pair in range(model.repetitions(self.suite["profile"])):
            expected.append(f"clients/{pair}")
            for group in model.groups(self.suite["profile"], pair):
                for index in range(group["density"] if group["arm"] == "native" else 1):
                    role = model.application_role(pair, group["ordinal"], group["arm"], index)
                    expected.append("owners/" + role)
                    if group["arm"] == "lsf":
                        expected.append("data/" + role)
        require([row["relative"] for row in self.suite["preparations"]] == expected,
                "kubernetes-closure-preparation-population")
        previous = self.suite["remote_create_call"]
        for row in self.suite["preparations"]:
            ordinal = integer(row["create_call"], 1, len(self.journal["rows"]) - 1)
            destination = model.host_path(self.suite["owner"], self.suite["run_id"], row["relative"])
            require(row["destination"] == destination and previous < ordinal - 1
                    and ordinal in self.used, "kubernetes-closure-preparation-order")
            parent = self.call(ordinal - 1, provider="docker", operation="worker-exec", timeout_seconds=20,
                argv=["mkdir", "-p", str(PurePosixPath(destination).parent)])
            require(not parent["stdout"], "kubernetes-closure-mkdir-output")
            needs_upload = not row["relative"].startswith("owners/")
            require((row["upload_call"] is not None) == needs_upload
                    and (row["transfer"] is not None) == needs_upload,
                    "kubernetes-closure-preparation-upload")
            previous = row["upload_call"] if needs_upload else ordinal

    def initialize(self):
        identity = self.call(0, provider="docker", operation="worker-identity")
        require(identity["owner"] == self.suite["owner"]
                and identity["response_json"]["Id"] == self.bootstrap["nodes"]["worker"]["container_id"],
                "kubernetes-closure-worker-identity")
        require(self.suite["remote_create_call"] == 1, "kubernetes-closure-initial-remote-order")
        made = self.call(self.suite["remote_create_call"], provider="docker", operation="worker-exec",
                         timeout_seconds=20, argv=["mkdir", "-m", "700", self.remote])
        require(not made["stdout"], "kubernetes-closure-mkdir-output")
        self.preparation_order()
        absent, created = self.suite["namespace_absence_call"], self.suite["namespace_create_call"]
        require(absent == self.suite["preparations"][1]["upload_call"] + 1 and created == absent + 1,
                "kubernetes-closure-namespace-order")
        self.call(absent, provider="kubernetes", method="GET", path=self.base, status=404,
                  timeout_seconds=15, expected_statuses=[404])
        call = self.call(created, provider="kubernetes", method="POST", path="/api/v1/namespaces", status=201,
                         timeout_seconds=15, expected_statuses=[201])
        desired = model.namespace(self.suite["owner"], self.suite["run_id"])
        _same(call["request_json"], desired, "kubernetes-closure-namespace-request")
        _same(call["response_json"], self.suite["namespace_create"], "kubernetes-closure-namespace-response")
        services.subset(call["response_json"], desired)
        require(call["response_json"]["metadata"]["uid"] == self.suite["namespace_uid"]
                and call["response_json"]["metadata"].get("deletionTimestamp") is None,
                "kubernetes-closure-namespace-uid")

    def _command_time(self, pair, group, command):
        client = self.suite["clients"][pair]
        values = [row for row in client["commands"] if (item := decode(row["line"].encode(), 64 * 1024))["command"] == command
                  and item["group"] == group]
        require(len(values) == 1, "kubernetes-closure-client-command")
        return uint(values[0]["sent_nanos"])

    def background(self):
        planned = [("idle-before-start", None), ("idle-before-end", None)]
        for group in self.suite["groups"]:
            planned += [(f"pair-{group['pair']}-group-{group['group']}-ready", group),
                        (f"pair-{group['pair']}-group-{group['group']}-final", group)]
        planned += [("idle-after-start", None), ("idle-after-end", None)]
        require(len(self.suite["background"]) == len(planned), "kubernetes-closure-background-count")
        spans, previous = {}, self.time(self.suite["namespace_create_call"])
        for observation, (stage, group) in zip(self.suite["background"], planned):
            fields(observation, "stage observations")
            require(observation["stage"] == stage and len(observation["observations"]) == 2,
                    "kubernetes-closure-background-stage")
            if group is not None:
                ready = stage.endswith("-ready")
                _same(observation, group["cluster_before" if ready else "cluster_after"],
                      "kubernetes-closure-background-group")
                lower = uint(group["graph_ready_nanos"] if ready else group["windows"][-1]["finished_nanos"])
                upper = self._command_time(group["pair"], group["group"], "begin-group" if ready else "finish-group")
            elif stage.startswith("idle-before-"):
                lower = self.time(self.suite["namespace_create_call"])
                upper = self.time(self.suite["preparations"][2]["create_call"] - 1, "started_nanos")
            else:
                lower = self.time(self.suite["clients"][-1]["delete"]["absence_call"])
                upper = uint(self.suite["cleanup"]["started_nanos"])
            first = None
            require([row["role"] for row in observation["observations"]] == list(self.bootstrap["nodes"]),
                    "kubernetes-closure-background-node-order")
            for row in observation["observations"]:
                fields(row, "role container_id call stats observed_nanos")
                call = self.call(row["call"], provider="docker", operation="node-stats", role=row["role"])
                require(row["container_id"] == self.bootstrap["nodes"][row["role"]]["container_id"],
                        "kubernetes-closure-background-node")
                _same(call["response_json"], row["stats"], "kubernetes-closure-background-original")
                begin, end, observed = uint(call["started_nanos"]), uint(call["finished_nanos"]), uint(row["observed_nanos"])
                require(max(lower, previous) <= begin <= end <= observed <= upper,
                        "kubernetes-closure-background-clock")
                first = begin if first is None else first
                previous = observed
            spans[stage] = (first, previous)
        for prefix in ("idle-before", "idle-after"):
            require(spans[prefix + "-end"][0] - spans[prefix + "-start"][1] >= 250_000_000,
                    "kubernetes-closure-background-baseline-window")

    def _poll_window(self, parent, *, first, last, lower, phase, deletion=False):
        pod = parent["create"]["pod"]
        metadata = pod["metadata"]
        path = self.base + "/pods/" + metadata["name"]
        indices = [index for index in self.polls[path] if first < index <= last]
        require(indices and indices[-1] == last and len(indices) <= (600 if deletion else 1200),
                "kubernetes-closure-poll-population")
        for index in indices:
            selected = self.call(index, consume=False, provider="kubernetes", method="GET", path=path,
                timeout_seconds=15, expected_statuses=[200, 404] if deletion else [200])
            raw, value = selected["raw"], selected["response_json"]
            require(uint(selected["started_nanos"]) >= lower, "kubernetes-closure-poll-clock")
            if deletion and index == last:
                require(raw["status"] == 404, "kubernetes-closure-poll-absence")
            else:
                require(raw["status"] == 200 and value.get("kind") == "Pod"
                        and all(value["metadata"].get(key) == metadata[key] for key in ("name", "namespace", "uid")),
                        "kubernetes-closure-poll-owner")
                services.subset(value["metadata"]["labels"], model.labels(self.suite["owner"], self.suite["run_id"], metadata["name"]))
                status = value.get("status", {})
                states = status.get("containerStatuses", [])
                require(isinstance(states, list) and len(states) <= 1 and status.get("phase") != "Failed"
                        and all(type(row["restartCount"]) is int and row["restartCount"] == 0 for row in states),
                        "kubernetes-closure-poll-restart")
                if not deletion:
                    completed = status.get("phase") == phase and len(states) == 1 and (
                        states[0].get("ready") is True and states[0].get("started") is True if phase == "Running"
                        else type(states[0].get("state", {}).get("terminated", {}).get("exitCode")) is int
                        and states[0]["state"]["terminated"]["exitCode"] == 0)
                    require(completed == (index == last), "kubernetes-closure-poll-after-success")
            self.used.add(index)

    def polling(self):
        parents = [(row, True) for row in self.suite["clients"]]
        parents += [(row, False) for group in self.suite["groups"] for row in group["owners"]]
        for parent, client in parents:
            ready = parent["ready"]["call"] if client else parent["ready_call"]
            final = parent["final"]["call"] if client else parent["final_call"]
            self._poll_window(parent, first=parent["create"]["call"], last=ready,
                lower=self.time(parent["create"]["call"]), phase="Running")
            self._poll_window(parent, first=ready, last=final,
                lower=uint(parent["attach"]["finished_nanos"] if client else parent["event_observations"][-1]["observed_nanos"]),
                phase="Succeeded")
            self._poll_window(parent, first=parent["delete"]["call"], last=parent["delete"]["absence_call"],
                lower=self.time(parent["delete"]["call"]), phase="Succeeded", deletion=True)

    def progress(self):
        expected, preparations = [], iter(self.suite["preparations"])

        def emit(kind, value, lower=None, upper=None):
            expected.append((kind, value, self.lower if lower is None else lower, self.upper if upper is None else upper))

        def prepared():
            row = next(preparations)
            emit("directory-prepared", row, self.time(row["upload_call"] if row["upload_call"] is not None else row["create_call"]))

        def created(parent):
            emit("pod-create-attempt", parent["manifest"], upper=self.time(parent["create"]["call"], "started_nanos"))
            emit("pod-created", parent["create"], uint(parent["create"]["observed_nanos"]))

        prepared()
        prepared()
        for pair, client in enumerate(self.suite["clients"]):
            prepared()
            created(client)
            names = "pair plan directory parent_directory remote_directory manifest create".split()
            emit("client-created", {key: client[key] for key in names}, uint(client["create"]["observed_nanos"]),
                 self.time(client["ready"]["call"], "started_nanos"))
            attachment = client["attach"]
            emit("client-attached", {"pair": pair, **{key: attachment[key] for key in ("argv", "process_id", "start_time_ticks")}},
                 uint(attachment["started_nanos"]), uint(client["observations"][0]["observed_nanos"]))
            for group in [row for row in self.suite["groups"] if row["pair"] == pair]:
                for parent in group["owners"]:
                    prepared()
                    if group["arm"] == "lsf":
                        prepared()
                for parent in group["owners"]:
                    created(parent)
                for parent in group["owners"]:
                    names = ("role arm density manifest template_copy remote_output remote_data directory create pod_ready ready_call "
                             "cri_ready cri_ready_call identity_call start_time_ticks app_process_id owner_ref container_id").split()
                    emit("application-ready", {key: parent[key] for key in names}, self.time(parent["identity_call"]),
                         self.time(group["graph_attempts"][0]["pods_call"], "started_nanos"))
                for index in range(6):
                    for parent in group["owners"]:
                        row = parent["snapshots"][index]
                        emit("application-snapshot", {"container_id": parent["container_id"], **row}, uint(row["node_finished_nanos"]))
                emit("group-complete", {key: group[key] for key in ("pair", "group", "arm", "density")}, uint(group["finished_nanos"]))
            emit("client-complete-before-delete", {key: value for key, value in client.items() if key != "delete"},
                 self.time(client["download"]["call"]), self.time(client["delete"]["call"], "started_nanos"))
        require(next(preparations, None) is None, "kubernetes-closure-extra-preparation")
        _progress(self.root / "progress.ndjson", expected, self.lower, self.upper)


def validate(suite, root, journal, bootstrap, used_set):
    """Mutate only the caller's consumed-ordinal set; no filesystem/API writes."""
    closure = Closure(suite, root, journal, bootstrap, used_set)
    closure.initialize()
    closure.background()
    closure.polling()
    closure.progress()
    require(used_set == set(range(len(journal["rows"]))), "kubernetes-closure-unconsumed-call")
