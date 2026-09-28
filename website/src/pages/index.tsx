import React from 'react';
import Layout from '@theme/Layout';
import Link from '@docusaurus/Link';

const sections = [
  ['Start', '/docs/start/', 'Install the developer tools, create an application and run its tests.'],
  ['Learn', '/docs/component-development/creating-a-capsule/', 'Build a greeting service, a word counter and a shipping calculator.'],
  ['How-to', '/docs/how-to/developer-commands/', 'Find developer commands, web delivery, container operations and recovery procedures.'],
  ['Reference', '/docs/reference/operator-cli/', 'Consult CLI, API, configuration and protocol references.'],
  ['Understand', '/docs/architecture/overview/', 'Learn how execution, permissions and resources fit together.'],
  ['Contribute', '/docs/contribute/', 'Set up a checkout, make a change, run checks and open a pull request.'],
];

export default function Home(): React.ReactNode {
  return <Layout title="LSF documentation" description="Build capsules in six languages, deliver websites and operate an LSF node.">
    <main className="container foundation-home">
      <p className="lsf-eyebrow">Bounded execution. Explicit authority.</p>
      <h1>Latent Service Fabric documentation</h1>
      <p>Build capsules in Rust, C, TypeScript, Go, Java or C#. The packaged developer tools create your workspace and manage build, test and edit/watch on an LSF node.</p>
      <p><Link className="button button--primary" to="/docs/start/application-development/">Create your first application</Link></p>
      <p>Have an existing frontend? <Link to="/docs/how-to/deliver-a-website/">Deliver a website</Link> with the static Angular/PrimeNG or Docusaurus recipes, then publish and recover updates independently of your node.</p>
      <p><Link className="button button--primary margin-right--sm" to="/guides/">Find a guide by task</Link> <Link to="/search/">Search documentation</Link></p>
      <p>Use the version menu to choose a released documentation snapshot or the current development guides. Each snapshot keeps its own examples and supported features.</p>
      <div className="foundation-grid">{sections.map(([label, route, description]) =>
        <section key={label}><h2><Link to={route}>{label}</Link></h2><p>{description}</p></section>,
      )}</div>
      <p>Working on LSF itself? Read the <Link to="/decisions/">architecture decisions</Link> and the <Link to="/docs/contribute/">contribution guide</Link>.</p>
    </main>
  </Layout>;
}
