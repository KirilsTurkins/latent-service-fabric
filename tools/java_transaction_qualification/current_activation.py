"""Select one signed runtime after its ordinary current deployment mutation."""
from __future__ import annotations

import copy

from tools.phase2_operator_process import read_json

from . import configuration as cfg, lifecycle
from .inputs import require


class CurrentActivation:
    def __init__(self, client, configuration, node, signed, items, publications, proposals, inspected_path):
        require(client.phase4 and node.current_publication_program
                and configuration.value['state']['formatVersion'] == 2,
                'explicit-current-publication-program')
        self.client, self.configuration, self.node, self.signed = client, configuration, node, signed
        self.items = {item.name: item for item in items}
        self.publications, self.proposals = publications, proposals
        self.operations = copy.deepcopy(read_json(inspected_path)['state']['operations'])
        require(len(self.operations) == 15, 'current-six-capture-runtime-registry')
        self.metadata, self.active = {}, None

    def path(self, name):
        item, publication = self.items[name], self.publications[name]
        operations = cfg.active_operations(self.operations, publication, item.component_digest)
        path = self.configuration.path.parent / ('active-' + name + '-node.json')
        expected = dict(self.configuration.value)
        expected['state'] = dict(expected['state'], operations=operations)
        if path.exists():
            require(not path.is_symlink() and read_json(path) == expected, 'unchanged-current-runtime-selection')
            return path
        return self.configuration.selected(path, operations)

    def select_metadata(self, name, session):
        require(self.node.process is None, 'metadata-mutation-requires-retired-runtime')
        self.node.start(self.configuration.path, current_session=session)
        try:
            self.metadata[name] = lifecycle.deployment_metadata(self.client, self.signed, self.items[name],
                self.publications[name], self.proposals['deploymentGrants'])
        finally:
            self.node.stop()
        lifecycle.admission_lease_interval(self.client)
        return self.path(name)

    def start(self, campaign, name, session):
        require(name in self.metadata and self.node.process is None, 'current-deployment-before-runtime-start')
        path = self.path(name)
        self.node.start(path, current_session=session)
        deployed, target = self.metadata[name]
        lifecycle.bind_http_routes(self.client, self.configuration.authority, self.items[name], target)
        self.active = name
        if campaign is not None:
            campaign.full_path = path
        self.client.evidence.passed('deploy-' + name, {'deployment': deployed, 'selectedTarget': target})
        return target

    def switch(self, campaign, name):
        if self.active == name and self.node.process is not None:
            require(campaign.full_path == self.path(name), 'same-current-runtime-configuration')
            return self.metadata[name][1]
        sessions = {
            'put-once-diagnostics': ('diagnostic-metadata', 'diagnostic-runtime'),
            'put-once-legacy-v1': ('legacy-metadata', 'legacy-after-diagnostic'),
            'put-once-compatible-v2': ('compatible-metadata', 'compatible-runtime'),
        }
        require(name in sessions, 'bounded-current-publication-transition')
        if self.node.process is not None:
            self.node.stop()
        lifecycle.admission_lease_interval(self.client)
        metadata, runtime = sessions[name]
        self.select_metadata(name, metadata)
        return self.start(campaign, name, runtime)
