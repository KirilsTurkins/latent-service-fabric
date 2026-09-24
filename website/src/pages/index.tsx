import React from 'react';
import Layout from '@theme/Layout';
import Link from '@docusaurus/Link';

const sections = [
  ['Start', '/docs/start/', 'Create a node and run your first program.'],
  ['Learn', '/docs/component-development/creating-a-capsule/', 'Build a greeting service, a word counter and a shipping calculator.'],
  ['How-to', '/docs/phase-2-operator-workflows/', 'Find delivery, rollout and recovery procedures.'],
  ['Reference', '/docs/reference/operator-cli/', 'Consult CLI, API, configuration and protocol references.'],
  ['Understand', '/docs/architecture/overview/', 'Learn how execution, permissions and resources fit together.'],
  ['Contribute', '/docs/contribute/', 'Set up a checkout, make a change, run checks and open a pull request.'],
];

export default function Home(): React.ReactNode {
  return <Layout title="LSF documentation" description="Learn to create a node, build capsules, connect clients and serve Angular applications.">
    <main className="container foundation-home">
      <p className="lsf-eyebrow">Bounded execution. Explicit authority.</p>
      <h1>Latent Service Fabric documentation</h1>
      <p>Run small programs on an LSF node and call them from your applications. Start by creating a node, then build and deploy your own capsules.</p>
      <p><Link className="button button--primary margin-right--sm" to="/guides/">Find a guide by task</Link> <Link to="/search/">Search documentation</Link></p>
      <p>The development channel includes work in progress. The version menu also provides the preserved <strong>0.1.0-alpha.3</strong> documentation.</p>
      <div className="foundation-grid">{sections.map(([label, route, description]) =>
        <section key={label}><h2><Link to={route}>{label}</Link></h2><p>{description}</p></section>,
      )}</div>
      <p>Working on LSF itself? Read the <Link to="/decisions/">architecture decisions</Link> and the <Link to="/docs/contribute/">contribution guide</Link>.</p>
    </main>
  </Layout>;
}
