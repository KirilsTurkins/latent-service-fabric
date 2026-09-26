import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {test} from 'node:test';
import {createRepositoryIndex, websiteRoot} from '../lib/repository.mjs';
import {validateCoverage} from '../lib/coverage.mjs';

const index = createRepositoryIndex();
const original = JSON.parse(fs.readFileSync(path.join(websiteRoot, 'content/coverage.json'), 'utf8'));

test('the accepted inventory retains every required outcome and pending reviews still block publication', () => {
  assert.deepEqual(validateCoverage(original, index, {acceptance: true}), {rows: 27, pendingHumanReview: 0, acceptance: true});
  const pending = structuredClone(original);
  pending.rows[0].review = {...pending.rows[0].review, status: 'pending', reviewedCommit: null, criteria: []};
  assert.throws(() => validateCoverage(pending, index, {acceptance: true}), /human guide\/execution review/);
});

test('missing and duplicate finite IDs fail', () => {
  const missing = structuredClone(original);
  missing.rows.pop();
  assert.throws(() => validateCoverage(missing, index), /finite coverage identifier/);
  const duplicate = structuredClone(original);
  duplicate.rows[1].id = duplicate.rows[0].id;
  assert.throws(() => validateCoverage(duplicate, index), /Duplicate coverage/);
});

test('nonexistent or nonpublished pages, wrong-case sources and incomplete required rows fail', () => {
  for (const change of [
    document => { document.rows[0].pages[0].path = 'docs/does-not-exist.md'; },
    document => { document.rows[0].pages[0].path = 'README.md'; },
    document => { document.rows[0].sourceRefs = ['security.md']; },
    document => { document.rows[0].implementationPrerequisites = []; },
    document => { document.rows[0].evidence[0].path = '../secret'; },
    document => { document.rows[0].guideIssue = 345; },
    document => { document.rows[0].implementationPrerequisites = [237]; },
    document => { document.rows[0].implementationPrerequisites = [240]; },
    document => { document.rows[0].implementationPrerequisites = [357]; },
  ]) {
    const document = structuredClone(original);
    change(document);
    assert.throws(() => validateCoverage(document, index));
  }
});

test('page existence or a test source cannot be promoted into reviewed execution evidence', () => {
  const document = structuredClone(original);
  // Keep the negative fixture incomplete as real guide rows gain evidence.
  for (const page of document.rows[0].pages) page.role = 'reference-only';
  document.rows[0].evidence = document.rows[0].evidence.filter(entry => entry.kind === 'test-source');
  document.rows[0].review.status = 'approved';
  document.rows[0].review.reviewedCommit = index.revision;
  document.rows[0].review.criteria = [];
  assert.throws(() => validateCoverage(document, index), /lacks a guide/);
  document.rows[0].pages[0].role = 'guide';
  assert.throws(() => validateCoverage(document, index), /Incomplete human authoring review/);
  document.rows[0].review.criteria = JSON.parse(fs.readFileSync(path.join(websiteRoot, 'content/coverage-contract.json'), 'utf8')).authoringCriteria;
  assert.throws(() => validateCoverage(document, index), /version-bound execution evidence/);
  document.rows[0].evidence[0].status = 'executed';
  assert.throws(() => validateCoverage(document, index), /Coverage schema/);
});
