import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { isTrustedPull, runPlan } from './plan.mjs';

const subscription = '11111111-1111-4111-8111-111111111111';
const sha = 'a'.repeat(40);
const event = {
  repository: { full_name: 'Ries630/AzureDataTransformationLab', owner: { login: 'Ries630' } },
  pull_request: { user: { login: 'Ries630' }, head: { sha, repo: { full_name: 'Ries630/AzureDataTransformationLab' } } },
};

/** PRコンテキストと機密入力を用意し、外部CLIだけを記録する。 */
function fixture(t) {
  const directory = mkdtempSync(join(tmpdir(), 'adtl-plan-test-'));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const root = join(directory, 'root');
  mkdirSync(root);
  const calls = [];
  const env = {
    GITHUB_EVENT_NAME: 'pull_request', GITHUB_REPOSITORY: event.repository.full_name,
    GITHUB_ACTOR: 'Ries630', EXPECTED_HEAD_SHA: sha, ARM_SUBSCRIPTION_ID: subscription,
    TERRAFORM_BACKEND_CONFIG: JSON.stringify({ subscription_id: subscription }),
    TERRAFORM_INPUTS: JSON.stringify({ subscription_id: subscription, resource_group_name: 'rg-test',
      storage_account_name: 'exampletest', operator_object_id: subscription }),
  };
  return { root, output: join(directory, 'plan.md'), event: structuredClone(event), env, calls,
    initialize: () => calls.push('init'),
    run: (program, args) => { calls.push([program, ...args]); return args.includes('show') ? '{}' : ''; },
    render: () => '<!-- terraform-plan:infra/terraform -->\n公開済みの形式\n',
  };
}

test('fork・他ユーザー・別イベント・別headでは機密入力を処理しない', (t) => {
  for (const scenario of ['fork', 'author', 'actor', 'event', 'sha']) {
    const f = fixture(t);
    if (scenario === 'fork') f.event.pull_request.head.repo.full_name = 'external/fork';
    if (scenario === 'author') f.event.pull_request.user.login = 'external';
    if (scenario === 'actor') f.env.GITHUB_ACTOR = 'external';
    if (scenario === 'event') f.env.GITHUB_EVENT_NAME = 'pull_request_target';
    if (scenario === 'sha') f.env.EXPECTED_HEAD_SHA = 'b'.repeat(40);
    assert.equal(isTrustedPull(f.event, f.env), false);
    assert.throws(() => runPlan(f));
    assert.deepEqual(f.calls, []);
  }
});

test('Subscriptionまたは操作ユーザーの指定が不正ならinit前に拒否する', (t) => {
  for (const scenario of ['subscription', 'operator']) {
    const f = fixture(t);
    const input = JSON.parse(f.env.TERRAFORM_INPUTS);
    if (scenario === 'subscription') input.subscription_id = '22222222-2222-4222-8222-222222222222';
    if (scenario === 'operator') delete input.operator_object_id;
    f.env.TERRAFORM_INPUTS = JSON.stringify(input);
    assert.throws(() => runPlan(f));
    assert.deepEqual(f.calls, []);
  }
});

test('既存state初期化からvalidate・saved plan・showを順に実行し公開用Markdownだけを残す', (t) => {
  const f = fixture(t);
  runPlan(f);
  assert.equal(f.calls[0], 'init');
  assert.deepEqual(f.calls.slice(1).map(call => call[2]), ['validate', 'plan', 'show']);
  assert.ok(f.calls[2].some(arg => arg.startsWith('-out=')));
  assert.ok(f.calls.every(call => !Array.isArray(call) || !call.includes('apply')));
  assert.ok(readFileSync(f.output, 'utf8').startsWith('<!-- terraform-plan:infra/terraform -->'));
  assert.throws(() => readFileSync(join(f.root, 'ci.auto.tfvars.json')));
});

test('plan取得失敗時は診断やJSONを公開せず終了する', (t) => {
  const f = fixture(t);
  f.run = () => { throw new Error('fake-private-diagnostic'); };
  assert.throws(() => runPlan(f));
  assert.throws(() => readFileSync(f.output));
  assert.throws(() => readFileSync(join(f.root, 'ci.auto.tfvars.json')));
});
