import fs from 'node:fs';
import path from 'node:path';
import Ajv from 'ajv/dist/2020.js';
import {canonicalPath, readSource, requireValue, websiteRoot} from './repository.mjs';

const schema = JSON.parse(fs.readFileSync(path.join(websiteRoot, 'content/coverage.schema.json'), 'utf8'));
const contract = JSON.parse(fs.readFileSync(path.join(websiteRoot, 'content/coverage-contract.json'), 'utf8'));
const validateSchema = new Ajv({allErrors: true, strict: true}).compile(schema);

export function validateCoverage(document, index, {acceptance = false} = {}) {
  requireValue(validateSchema(document), `Coverage schema: ${JSON.stringify(validateSchema.errors)}`);
  const identifiers = document.rows.map(row => row.id);
  requireValue(new Set(identifiers).size === identifiers.length, 'Duplicate coverage identifier');
  requireValue(JSON.stringify([...identifiers].sort()) === JSON.stringify([...contract.requiredIds].sort()), 'Missing or unexpected finite coverage identifier');
  let pending = 0;
  for (const row of document.rows) {
    requireValue(contract.areas.includes(row.area) && contract.guideIssues.includes(row.guideIssue), `Unknown area/guide owner: ${row.id}`);
    requireValue(row.implementationPrerequisites.every(ticket => ![201, 240, 345, ...contract.guideIssues].includes(ticket)), `Guide/gate issues are not implementation prerequisites: ${row.id}`);
    for (const reference of [...row.sourceRefs, ...row.evidence.map(entry => entry.path)]) {
      canonicalPath(reference);
      requireValue(index.paths.includes(reference) || index.directories.includes(reference), `Missing coverage source/evidence: ${reference}`);
      if (index.paths.includes(reference)) requireValue(readSource(index.root, reference).length > 0, `Empty coverage source/evidence: ${reference}`);
    }
    for (const page of row.pages) {
      requireValue(index.pages.some(entry => entry.source === page.path), `Coverage page is not published: ${page.path}`);
    }
    if (row.review.status === 'approved') {
      requireValue(row.pages.some(page => page.role === 'guide'), `Approved row lacks a guide: ${row.id}`);
      requireValue(JSON.stringify([...row.review.criteria].sort()) === JSON.stringify([...contract.authoringCriteria].sort()), `Incomplete human authoring review: ${row.id}`);
      requireValue(row.evidence.some(entry => entry.kind === 'execution-receipt' && entry.status === 'executed' && /^[a-f0-9]{40}$/.test(entry.sourceCommit ?? '')), `Approved row lacks version-bound execution evidence: ${row.id}`);
    } else pending += 1;
  }
  requireValue(!acceptance || pending === 0, `${pending} coverage rows still require human guide/execution review; page existence is not acceptance`);
  return {rows: document.rows.length, pendingHumanReview: pending, acceptance: pending === 0};
}
