import assert from 'node:assert/strict';
import { test } from 'node:test';
import { publishComment } from './comment.mjs';

const marker = '<!-- terraform-plan:infra/terraform -->';
const headSha = 'a'.repeat(40);

/** GitHub API境界を置き換え、PRとコメントの状態変化を観測する。 */
function apiFixture() {
  const comments = [{ id: 1, user: { login: 'someone', type: 'User' }, body: `${marker}\n手書きメモ` }];
  const pull = { state: 'open', head: { sha: headSha, repo: { full_name: 'owner/repo' } } };
  return {
    comments, pull,
    github: {
      paginate: async () => structuredClone(comments),
      rest: {
        pulls: { get: async () => ({ data: pull }) },
        issues: {
          listComments: async () => ({ data: comments }),
          createComment: async ({ body }) => {
            comments.push({ id: 2, body, user: { login: 'github-actions[bot]', type: 'Bot' } });
          },
          updateComment: async ({ comment_id, body }) => {
            comments.find((comment) => comment.id === comment_id).body = body;
          },
        },
      },
    },
  };
}

test('再実行はbotの専用コメント1件を更新し、人の同名メモには触れない', async () => {
  const fixture = apiFixture();
  const args = { github: fixture.github, owner: 'owner', repo: 'repo', number: 9, headSha };
  assert.deepEqual(await publishComment({ ...args, body: `${marker}\n初回` }), { status: 'created' });
  assert.deepEqual(await publishComment({ ...args, body: `${marker}\n更新` }), { status: 'updated' });
  assert.equal(fixture.comments.length, 2);
  assert.equal(fixture.comments[0].body, `${marker}\n手書きメモ`);
  assert.match(fixture.comments[1].body, /更新$/);
  assert.ok(fixture.comments[1].body.includes(headSha));
});

test('forkと古いheadの結果は投稿しない', async () => {
  for (const condition of ['fork', 'stale', 'closed']) {
    const fixture = apiFixture();
    if (condition === 'fork') fixture.pull.head.repo.full_name = 'other/repo';
    if (condition === 'stale') fixture.pull.head.sha = 'b'.repeat(40);
    if (condition === 'closed') fixture.pull.state = 'closed';
    assert.deepEqual(await publishComment({
      github: fixture.github, owner: 'owner', repo: 'repo', number: 9, headSha, body: `${marker}\n結果`,
    }), { status: 'skipped' });
    assert.equal(fixture.comments.length, 1);
  }
});
