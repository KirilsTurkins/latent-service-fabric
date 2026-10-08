"""Separate signed value round trips and strict child-import refusal programme."""
import json
import re
from tools.phase2_operator_process import read_json
from . import http, lifecycle
from .acceptance_inputs import CHILD, VALUE, SELECTORS, UNSIGNED, declaration
from .campaign import command_input, precondition, rpc_result
from .inputs import digest, require
from tools.rust_capsule_project import read_file, snapshot


def query_source_witness(project, value):
    source = project["src/dev/latent/app/Capsule.java"].decode("utf-8")
    require(source.count("BusinessError> query() {\n") == 1, "original-value-query-source")
    query = source.split("BusinessError> query() {\n", 1)[1].split("    @Override", 1)[0]
    require(digest(query.encode()) == "sha256:c71780376cd2e351f9448a00a3e384052041214b532964af2bef942ccd65160f",
            "reviewed-original-null-utf8-absence-query")
    literals = re.findall(r'private static final byte\[\] UTF8_VALUE = ("(?:[^"\\]|\\.)*")\.getBytes\(StandardCharsets\.UTF_8\);', source)
    require(len(literals) == 1, "original-value-java-literal")
    payload = json.loads(literals[0]).encode("utf-8")
    require(json.loads(payload) == [None, value["utf8Text"]]
            and digest(payload) == value["utf8PayloadDigest"], "original-value-query-payload")
    return {"sourceDigest": digest(project["src/dev/latent/app/Capsule.java"]),
            "queryBodyDigest": digest(query.encode()), "nullUtf8PayloadDigest": digest(payload),
            "sourceCheckIsNotExecution": True}


def value_roundtrip(command, initial, query, before, after, expected):
    aggregate = http.aggregate(command)
    queried = http.fresh_query(query)
    require(command["disposition"] == "committed" and aggregate["count"] == expected
            and aggregate["key-version"] == initial["key-version"] and len(command["effect-ids"]) == 1,
            "actual-full-width-value-command")
    # The guest reports its original read precondition. Only the subsequent
    # query can witness the new physical key version; neither is synthesized.
    require(queried["count"] == expected and "some" in queried["key-version"]
            and queried["key-version"] != initial["key-version"]
            and int(after["commandCount"]) == int(before["commandCount"]) + 1,
            "actual-value-query-and-original-key-precondition")
    return queried


class AcceptanceCampaign:
    def __init__(self, campaign):
        self.campaign = campaign
        self.client = campaign.client
        self.item = campaign.items[VALUE]
        files = snapshot(self.item.directory / "project")
        self.value = declaration(files["transaction-value-inputs.json"], files)
        self.query_source = query_source_witness(files, self.value)

    def execute(self):
        campaign = self.campaign
        publication = campaign.publications[VALUE]
        package = read_json(campaign.signed.parent / "package-fixture-receipt.json")
        child = campaign.items[CHILD]
        refused = [row for row in package["profileRejections"] if row["variant"] == CHILD]
        require(len(refused) == 1 and refused[0]["componentDigest"] == child.component_digest
                and refused[0]["stage"] == "native-contract-validation"
                and refused[0]["reason"] == "unsupported-host-import" and refused[0]["signed"] is False
                and refused[0]["signedNodeExecutionQualified"] is False,
                "actual-strict-child-profile-refusal")
        lifecycle.deploy(self.client, campaign.signed, self.item, publication,
                         campaign.proposals["deploymentGrants"], campaign.configuration.authority)
        before = lifecycle.inspect_namespace(self.client, publication)
        _, initial = campaign.query(0)
        require(initial["key-version"] == {"none": None} and before["commandCount"] == "0",
                "actual-value-namespace-starts-absent")
        observed = []
        for label in ("highBit", "unsignedMaximum"):
            key = "java-value-" + label.lower()
            expected = UNSIGNED[label]
            raw = command_input(int(SELECTORS[label]))
            result = campaign.result(campaign.socket("command", original_key=key, body=raw,
                                                     condition=precondition(initial)))
            aggregate = http.aggregate(result)
            require(result["disposition"] == "committed" and aggregate["count"] == expected
                    and aggregate["key-version"] == initial["key-version"] and len(result["effect-ids"]) == 1,
                    "actual-full-width-value-command")
            original = lifecycle.lookup(self.client, publication, key)
            rpc_result(original, result, publication, key)
            effect = campaign.wait_effect(publication, key, result)
            recipient = campaign.peer_record(result["effect-ids"][0])
            namespace = lifecycle.inspect_namespace(self.client, publication)
            query, queried = campaign.query(int(expected), minimum=result["state-view"])
            after_query = lifecycle.inspect_namespace(self.client, publication)
            value_roundtrip(result, initial, query, before, after_query, expected)
            require(namespace["commandCount"] == after_query["commandCount"]
                    and int(namespace["commandCount"]) == int(before["commandCount"]) + 1
                    and query["disposition"] == "query" and "some" in queried["key-version"]
                    and queried["key-version"] != initial["key-version"],
                    "actual-value-query-does-not-create-command")
            replay = campaign.result(campaign.socket("command", original_key=key, body=raw,
                                                     condition=precondition(initial)))
            http.replay(result, replay)
            http.replay(result, campaign.original(key))
            rpc_result(lifecycle.lookup(self.client, publication, key), result, publication, key)
            require(lifecycle.inspect_namespace(self.client, publication)["commandCount"] == namespace["commandCount"],
                    "actual-full-width-original-result-replay")
            require(campaign.peer_record(result["effect-ids"][0]) == recipient,
                    "value-replay-cannot-apply-recipient-twice")
            self.client.evidence.passed("signed-value-" + label, {
                "componentDigest": self.item.component_digest, "publication": publication,
                "originalClientKey": key, "command": result, "query": query,
                "originalCommandReceipt": original, "effect": effect, "recipient": recipient,
                "expectedUnsigned": expected, "queryGuestCheckedNullUtf8AndAbsence": True,
                "querySourceWitness": self.query_source,
                "declarationDigest": digest(read_file(self.item.directory / "project/transaction-value-inputs.json"))})
            observed.append({"label": label, "count": expected, "commandId": result["command-id"],
                             "attemptId": result["attempt-id"], "effectId": result["effect-ids"][0]})
            initial = queried
            before = after_query
        return {"programme": "signed-java-values-and-forbidden-child", "values": observed,
                "utf8PayloadDigest": self.value["utf8PayloadDigest"], "absentOptionalRequired": True,
                "actualChildProfileRejection": refused[0], "offlineNativeActions": 0,
                "schemaRestoreQualified": False, "crashOrCancellationQualified": False}
