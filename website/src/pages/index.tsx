import React from 'react';
import Layout from '@theme/Layout';
import Link from '@docusaurus/Link';

const sections = [
  ['Start', '/docs/development/standalone-quickstart/', 'Evaluate the supported standalone boundary and prerequisites.'],
  ['Learn', '/docs/component-development/creating-a-capsule/', 'Read the existing capsule workflow and owning contracts.'],
  ['How-to', '/docs/phase-2-operator-workflows/', 'Find delivery, rollout and recovery procedures.'],
  ['Reference', '/docs/reference/operator-cli/', 'Consult CLI, API, configuration and protocol references.'],
  ['Understand', '/docs/architecture/overview/', 'Trace authority, resource ownership and later-phase boundaries.'],
  ['Contribute', '/docs/development/ci-profiles/', 'Choose focused checks without bypassing product validation.'],
];

export default function Home(): React.ReactNode {
  return <Layout title="LSF documentation" description="Find LSF setup, capsule, client, provider and Angular documentation with explicit version and verification scope.">
    <main className="container foundation-home">
      <p className="lsf-eyebrow">Bounded execution. Explicit authority.</p>
      <h1>Latent Service Fabric documentation</h1>
      <p>Build capsules, connect clients and operate a bounded standalone node. Start with the supported alpha boundary and check each page’s version and verification scope.</p>
      <p><Link className="button button--primary margin-right--sm" to="/guides/">Find a guide by task</Link> <Link to="/search/">Search documentation</Link></p>
      <p>The development channel includes work in progress. The version menu also provides the preserved <strong>0.1.0-alpha.3</strong> documentation.</p>
      <div className="foundation-grid">{sections.map(([label, route, description]) =>
        <section key={label}><h2><Link to={route}>{label}</Link></h2><p>{description}</p></section>,
      )}</div>
      <p><Link to="/decisions/">Architecture decisions</Link> record constraints and status, not proof that a feature is delivered.</p>
      <p><Link to="/components/">Theme component review</Link> is a presentation fixture, not guide or runtime acceptance.</p>
    </main>
  </Layout>;
}
