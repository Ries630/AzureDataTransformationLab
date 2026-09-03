import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const credentialKeys = ['access_key', 'sas_token', 'client_secret', 'client_certificate', 'client_certificate_path', 'client_certificate_password'];

/** 実環境の設定を検証し、Terraformへ渡せる項目だけに限定する。 */
function readConfig(root, env) {
  const config = JSON.parse(readFileSync(join(root, 'backend.local.json'), 'utf8'));
  const fields = ['subscription_id', 'resource_group_name', 'storage_account_name', 'container_name', 'key'];
  if (Object.keys(config).length !== fields.length || fields.some((field) => typeof config[field] !== 'string') ||
      !uuid.test(config.subscription_id) ||
      config.subscription_id.toLowerCase() !== env.ARM_SUBSCRIPTION_ID?.toLowerCase() ||
      !/^[a-zA-Z0-9_.()-]{1,90}$/.test(config.resource_group_name) ||
      !/^[a-z0-9]{3,24}$/.test(config.storage_account_name) ||
      !/^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$/.test(config.container_name) ||
      !/^[a-zA-Z0-9][a-zA-Z0-9._/-]{0,255}$/.test(config.key) || config.key.includes('..') ||
      credentialKeys.some((key) => env[`ARM_${key.toUpperCase()}`])) {
    throw new Error('backend設定または認証方式が不正です。');
  }
  return config;
}

/** Azure上の保存先を照合し、state Blobの存在だけを読む。 */
function checkDestination(config, run, env) {
  const subscription = JSON.parse(run('az', ['account', 'show', '--subscription', config.subscription_id, '-o', 'json']));
  if (subscription.name !== 'Personal-Sandbox' || subscription.state !== 'Enabled' ||
      subscription.id?.toLowerCase() !== config.subscription_id.toLowerCase() ||
      !uuid.test(subscription.tenantId ?? '') ||
      (env.ARM_TENANT_ID && env.ARM_TENANT_ID.toLowerCase() !== subscription.tenantId.toLowerCase())) {
    throw new Error('Personal-Sandboxを確認できません。');
  }
  const account = JSON.parse(run('az', [
    'storage', 'account', 'show', '--subscription', config.subscription_id,
    '--resource-group', config.resource_group_name, '--name', config.storage_account_name, '-o', 'json',
  ]));
  const expected = `/subscriptions/${config.subscription_id}/resourceGroups/${config.resource_group_name}/providers/Microsoft.Storage/storageAccounts/${config.storage_account_name}`;
  if (account.id?.toLowerCase() !== expected.toLowerCase() || account.isHnsEnabled !== false ||
      account.sku?.name !== 'Standard_LRS' || account.allowSharedKeyAccess !== false ||
      account.allowBlobPublicAccess !== false || account.enableHttpsTrafficOnly !== true ||
      account.minimumTlsVersion !== 'TLS1_2' || account.tags?.project !== 'AzureDataTransformationLab' ||
      account.tags?.purpose !== 'terraform-state') throw new Error('state保存先の構成が一致しません。');
  const properties = JSON.parse(run('az', [
    'storage', 'account', 'blob-service-properties', 'show', '--subscription', config.subscription_id,
    '--resource-group', config.resource_group_name, '--account-name', config.storage_account_name, '-o', 'json',
  ]));
  if (properties.isVersioningEnabled !== true || properties.deleteRetentionPolicy?.enabled !== true ||
      !(properties.deleteRetentionPolicy.days > 0) || properties.containerDeleteRetentionPolicy?.enabled !== true ||
      !(properties.containerDeleteRetentionPolicy.days > 0)) throw new Error('stateの復旧設定を確認できません。');
  const container = JSON.parse(run('az', [
    'rest', '--method', 'get', '--subscription', config.subscription_id, '--url',
    `https://management.azure.com${expected}/blobServices/default/containers/${config.container_name}?api-version=2025-08-01`, '-o', 'json',
  ]));
  if (container.properties?.publicAccess !== 'None') throw new Error('state containerが非公開ではありません。');
  const locks = JSON.parse(run('az', [
    'lock', 'list', '--subscription', config.subscription_id, '--resource', expected, '-o', 'json',
  ]));
  if (!Array.isArray(locks) || !locks.some((lock) => lock.level === 'CanNotDelete' &&
      lock.id?.toLowerCase().startsWith(`${expected}/providers/Microsoft.Authorization/locks/`.toLowerCase()))) {
    throw new Error('state保存先の削除ロックを確認できません。');
  }
  const exists = JSON.parse(run('az', [
    'storage', 'blob', 'exists', '--subscription', config.subscription_id,
    '--account-name', config.storage_account_name, '--container-name', config.container_name,
    '--name', config.key, '--auth-mode', 'login', '--query', 'exists', '-o', 'json',
  ]));
  if (typeof exists !== 'boolean') throw new Error('stateの存在を確認できません。');
  return { exists, tenantId: subscription.tenantId };
}

/** 属性順序に依存しない比較用表現を作る。 */
function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonical(value[key])]));
  }
  return value;
}

/** stateの同一性を、機密属性を公開せず比較できる形にする。 */
function fingerprint(state, subscription) {
  const managedResources = state.resources?.filter((resource) => resource.mode === 'managed')
    .reduce((count, resource) => count + (resource.instances?.length ?? 0), 0);
  if (state.version !== 4 || !uuid.test(state.lineage ?? '') ||
      !Number.isInteger(state.serial) || state.serial < 0 || !managedResources) {
    throw new Error('有効な既存stateが必要です。空stateでは移行できません。');
  }
  checkSubscriptionAttributes(state, subscription);
  const serialized = JSON.stringify(canonical({
    lineage: state.lineage, serial: state.serial, resources: state.resources, outputs: state.outputs,
  }));
  for (const match of serialized.matchAll(/\/subscriptions\/([0-9a-f-]{36})/gi)) {
    if (match[1].toLowerCase() !== subscription.toLowerCase()) throw new Error('stateに対象外Subscriptionがあります。');
  }
  return { sha256: createHash('sha256').update(serialized).digest('hex'), managedResources };
}

/** Resource ID以外のSubscription属性にも別環境が紛れていないか確認する。 */
function checkSubscriptionAttributes(value, subscription) {
  if (!value || typeof value !== 'object') return;
  for (const [key, item] of Object.entries(value)) {
    if (['subscription_id', 'subscriptionId'].includes(key) && item != null &&
        (typeof item !== 'string' || item.toLowerCase() !== subscription.toLowerCase())) {
      throw new Error('stateのSubscription属性が一致しません。');
    }
    checkSubscriptionAttributes(item, subscription);
  }
}

/** backendのキャッシュが期待する保存先を指すことを確認する。 */
function checkCache(root, config, type, tenantId) {
  const cache = JSON.parse(readFileSync(join(root, '.terraform/terraform.tfstate'), 'utf8')).backend;
  if (cache?.type !== type || (type === 'azurerm' && (
    cache.config?.storage_account_name !== config.storage_account_name ||
    cache.config?.subscription_id?.toLowerCase() !== config.subscription_id.toLowerCase() ||
    cache.config?.resource_group_name?.toLowerCase() !== config.resource_group_name.toLowerCase() ||
    (cache.config?.tenant_id && cache.config.tenant_id.toLowerCase() !== tenantId.toLowerCase()) ||
    credentialKeys.some((key) => cache.config?.[key]) ||
    cache.config?.container_name !== config.container_name || cache.config?.key !== config.key ||
    cache.config?.use_azuread_auth !== true
  ))) throw new Error('初期化済みbackendの保存先が一致しません。');
}

/** 移行準備・既存remote stateの初期化・移行後照合を実行する。Azureへのstate転送は行わない。 */
export function runBackend(command, { root, env = process.env, run = execute } = {}) {
  if (!['init', 'prepare-migration', 'verify-migration'].includes(command)) throw new Error('操作を指定してください。');
  root = resolve(root ?? 'infra/terraform');
  const config = readConfig(root, env);
  const { exists, tenantId } = checkDestination(config, run, env);
  const backendPath = join(root, 'remote.backend.hcl');
  const backendText = Object.entries(config).map(([key, value]) => `${key} = ${JSON.stringify(value)}`).join('\n') + '\n';

  if (command === 'prepare-migration') {
    if (exists) throw new Error('既存remote stateへの上書きを拒否しました。');
    checkCache(root, config, 'local');
    const source = readFileSync(join(root, 'terraform.tfstate'));
    const baseline = fingerprint(JSON.parse(source), config.subscription_id);
    const backupRoot = join(root, '.state-backups');
    mkdirSync(backupRoot, { recursive: true, mode: 0o700 });
    chmodSync(backupRoot, 0o700);
    const backupDirectory = mkdtempSync(join(backupRoot, 'migration-'));
    writeFileSync(join(backupDirectory, 'terraform.tfstate'), source, { mode: 0o600, flag: 'wx' });
    writeFileSync(join(backupDirectory, 'backend-cache.json'), readFileSync(join(root, '.terraform/terraform.tfstate')), { mode: 0o600, flag: 'wx' });
    writeFileSync(join(backupRoot, 'baseline.json'), JSON.stringify({ ...baseline, backupDirectory }), { mode: 0o600 });
    chmodSync(join(backupRoot, 'baseline.json'), 0o600);
    writeFileSync(backendPath, backendText, { mode: 0o600 });
    chmodSync(backendPath, 0o600);
    return { backupDirectory, managedResources: baseline.managedResources };
  }

  if (!exists) throw new Error('remote stateが存在しません。空stateへのフォールバックを拒否しました。');
  if (command === 'init') {
    writeFileSync(backendPath, backendText, { mode: 0o600 });
    chmodSync(backendPath, 0o600);
    run('terraform', [`-chdir=${root}`, 'init', '-input=false', '-reconfigure', '-lockfile=readonly', `-backend-config=${backendPath}`]);
    checkCache(root, config, 'azurerm', tenantId);
    fingerprint(JSON.parse(run('terraform', [`-chdir=${root}`, 'state', 'pull'])), config.subscription_id);
    return { initialized: true };
  }
  checkCache(root, config, 'azurerm', tenantId);
  const current = fingerprint(JSON.parse(run('terraform', [`-chdir=${root}`, 'state', 'pull'])), config.subscription_id);
  const baseline = JSON.parse(readFileSync(join(root, '.state-backups/baseline.json'), 'utf8'));
  const backup = fingerprint(JSON.parse(readFileSync(join(baseline.backupDirectory, 'terraform.tfstate'), 'utf8')), config.subscription_id);
  if (current.sha256 !== baseline.sha256 || backup.sha256 !== baseline.sha256) throw new Error('移行前後のstateと退避元が一致しません。');
  return { verified: true, managedResources: current.managedResources };
}

/** 外部CLIの診断を公開ログへ漏らさず、失敗時は呼び出し元へ伝える。 */
function execute(program, args) {
  return execFileSync(program, args, { encoding: 'utf8', maxBuffer: 32 * 1024 * 1024, stdio: ['ignore', 'pipe', 'pipe'] });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    console.log(JSON.stringify(runBackend(process.argv[2], { root: process.argv[3] })));
  } catch {
    console.error('backend操作を中止しました。設定・対象・state・認証を確認してください。');
    process.exitCode = 1;
  }
}
