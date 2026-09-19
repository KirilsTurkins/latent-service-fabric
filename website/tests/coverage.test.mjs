import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {test} from 'node:test';
import {createRepositoryIndex, websiteRoot} from '../lib/repository.mjs';
import {validateCoverage} from '../lib/coverage.mjs';

const index = createRepositoryIndex();
const original = JSON.parse(fs.readFileSync(path.join(websiteRoot, 'content/coverage.json'), 'utf8'));

test('the finite live-source inventory maps all required outcomes without claiming guide acceptance', () => {
  assert.deepEqual(validateCoverage(original, index), {rows: 27, pendingHumanReview: 27, acceptance: false});
  assert.throws(() => validateCoverage(original, index, {acceptance: true}), /human guide\/execution review/);
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
  ]) {
    const document = structuredClone(original);
    change(document);
    assert.throws(() => validateCoverage(document, index));
  }
});

test('page existence or a test source cannot be promoted into reviewed execution evidence', () => {
  const document = structuredClone(original);
  document.rows[0].review.status = 'approved';
  document.rows[0].review.reviewedCommit = index.revision;
  assert.throws(() => validateCoverage(document, index), /lacks a guide/);
  document.rows[0].pages[0].role = 'guide';
  assert.throws(() => validateCoverage(document, index), /Incomplete human authoring review/);
  document.rows[0].review.criteria = JSON.parse(fs.readFileSync(path.join(websiteRoot, 'content/coverage-contract.json'), 'utf8')).authoringCriteria;
  assert.throws(() => validateCoverage(document, index), /version-bound execution evidence/);
  document.rows[0].evidence[0].status = 'executed';
  assert.throws(() => validateCoverage(document, index), /Coverage schema/);
});
