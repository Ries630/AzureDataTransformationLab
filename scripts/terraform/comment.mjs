const marker = '<!-- terraform-plan:infra/terraform -->';

/** 現在のPR headに対し、このworkflow専用のbotコメントだけを更新する。 */
export async function publishComment({ github, owner, repo, number, headSha, body }) {
  if (!body.startsWith(`${marker}\n`) || Buffer.byteLength(body, 'utf8') > 60_000) {
    throw new Error('公開用レポートの形式が不正です。');
  }
  if (!/^[0-9a-f]{40}$/i.test(headSha)) throw new Error('PR headのSHAが不正です。');
  const { data: pull } = await github.rest.pulls.get({ owner, repo, pull_number: number });
  if (pull.state !== 'open' || pull.head.sha !== headSha ||
      pull.head.repo?.full_name !== `${owner}/${repo}`) {
    return { status: 'skipped' };
  }
  const comments = await github.paginate(github.rest.issues.listComments, {
    owner, repo, issue_number: number, per_page: 100,
  });
  const ownComments = comments.filter((comment) =>
    comment.user?.login === 'github-actions[bot]' &&
    comment.user?.type === 'Bot' && comment.body?.startsWith(`${marker}\n`));
  if (ownComments.length > 1) throw new Error('専用コメントが複数あるため更新を中止します。');
  const annotatedBody = body.replace(`${marker}\n`, `${marker}\n対象コミット: \`${headSha}\`\n`);
  if (ownComments.length === 1) {
    await github.rest.issues.updateComment({ owner, repo, comment_id: ownComments[0].id, body: annotatedBody });
    return { status: 'updated' };
  }
  await github.rest.issues.createComment({ owner, repo, issue_number: number, body: annotatedBody });
  return { status: 'created' };
}
