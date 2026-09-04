import { execFileSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { runBackend } from './backend.mjs';
import { renderReport } from './report.mjs';

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** 所有者の同一リポジトリPRだけを許可し、workflowの入口でも使う。 */
export function isTrustedPull(event, env = process.env) {
  const pull = event.pull_request;
  return env.GITHUB_EVENT_NAME === 'pull_request' &&
    event.repository?.full_name === 'Ries630/AzureDataTransformationLab' &&
    event.repository.full_name === env.GITHUB_REPOSITORY &&
    pull?.head?.repo?.full_name === env.GITHUB_REPOSITORY &&
    pull.user?.login === event.repository.owner.login &&
    env.GITHUB_ACTOR === event.repository.owner.login &&
    /^[0-9a-f]{40}$/i.test(env.EXPECTED_HEAD_SHA ?? '') && pull.head.sha === env.EXPECTED_HEAD_SHA;
}

/** CIの機密入力からsaved planを生成し、検証済みMarkdownだけを残す。 */
export function runPlan({ root = 'infra/terraform', output, event, env = process.env,
  initialize = runBackend, run = execute, render = renderReport } = {}) {
  if (!isTrustedPull(event, env)) throw new Error('信頼できるPRではありません。');
  const inputs = JSON.parse(env.TERRAFORM_INPUTS);
  const backend = JSON.parse(env.TERRAFORM_BACKEND_CONFIG);
  const allowed = ['subscription_id', 'operator_object_id', 'resource_group_name', 'storage_account_name', 'location', 'tags'];
  if (!uuid.test(env.ARM_SUBSCRIPTION_ID ?? '') || inputs.subscription_id !== env.ARM_SUBSCRIPTION_ID ||
      backend.subscription_id !== env.ARM_SUBSCRIPTION_ID || !uuid.test(inputs.operator_object_id ?? '') ||
      typeof inputs.resource_group_name !== 'string' || typeof inputs.storage_account_name !== 'string' ||
      Object.keys(inputs).some(key => !allowed.includes(key))) throw new Error('planの入力が不正です。');
  root = resolve(root);
  const directory = mkdtempSync(join(tmpdir(), 'adtl-private-plan-'));
  const ownedFiles = [];
  try {
    for (const [name, value] of [['backend.local.json', backend], ['ci.auto.tfvars.json', inputs]]) {
      const path = join(root, name);
      writeFileSync(path, JSON.stringify(value), { mode: 0o600, flag: 'wx' });
      ownedFiles.push(path);
    }
    const call = (program, args) => run(program, args, env);
    initialize('init', { root, env, run: call });
    call('terraform', [`-chdir=${root}`, 'validate', '-no-color']);
    const saved = join(directory, 'plan.tfplan');
    call('terraform', [`-chdir=${root}`, 'plan', '-input=false', '-no-color', '-lock-timeout=60s', `-out=${saved}`]);
    const plan = JSON.parse(call('terraform', [`-chdir=${root}`, 'show', '-json', saved]));
    const body = render(plan, env.ARM_SUBSCRIPTION_ID, env.TFPLAN2MD_PATH);
    mkdirSync(dirname(output), { recursive: true, mode: 0o700 });
    writeFileSync(output, body, { mode: 0o600, flag: 'wx' });
  } finally {
    for (const path of ownedFiles) rmSync(path, { force: true });
    rmSync(directory, { recursive: true, force: true });
  }
}

/** TerraformやAzure CLIの生ログを公開せず、成否だけを呼び出し元へ返す。 */
function execute(program, args, env) {
  return execFileSync(program, args, { env, encoding: 'utf8', maxBuffer: 32 * 1024 * 1024,
    stdio: ['ignore', 'pipe', 'pipe'] });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const event = JSON.parse(readFileSync(process.env.GITHUB_EVENT_PATH, 'utf8'));
    if (process.argv[2] === 'check-context') {
      if (!isTrustedPull(event)) throw new Error('信頼できるPRではありません。');
    } else {
      runPlan({ event, output: process.argv[2] });
    }
  } catch {
    console.error('PRのplan処理を中止しました。実行コンテキスト・設定・権限を確認してください。');
    process.exitCode = 1;
  }
}
