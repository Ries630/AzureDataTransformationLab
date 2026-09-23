import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, existsSync, rmSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { runBackend } from './backend.mjs';

const subscription = '11111111-1111-4111-8111-111111111111';

/** Azure CLIとTerraformだけを置き換え、stateの移行準備をファイル境界で検証する。 */
function fixture(t) {
  const root = mkdtempSync(join(tmpdir(), 'adtl-backend-test-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const config = {
    subscription_id: subscription, resource_group_name: 'rg-state-test',
    storage_account_name: 'adtlstatetest', container_name: 'tfstate', key: 'lab.terraform.tfstate',
  };
  const state = {
    version: 4, lineage: '22222222-2222-4222-8222-222222222222', serial: 8, outputs: {},
    resources: [{ mode: 'managed', type: 'azurerm_resource_group', name: 'lab', instances: [{
      attributes: { id: `/subscriptions/${subscription}/resourceGroups/rg-lab`, token: 'fake-sensitive-state' },
    }] }],
  };
  mkdirSync(join(root, '.terraform'));
  writeFileSync(join(root, '.terraform/terraform.tfstate'), JSON.stringify({ backend: { type: 'local' } }));
  writeFileSync(join(root, 'terraform.tfstate'), JSON.stringify(state));
  writeFileSync(join(root, 'backend.local.json'), JSON.stringify(config));
  const remote = { exists: false, name: 'Personal-Sandbox', state, config, publicAccess: 'None', versioning: true, locked: true };
  const calls = [];
  /** CLIの読み取り結果と初期化によるキャッシュ更新を再現する。 */
  function run(program, args) {
    calls.push([program, ...args]);
    if (program === 'az' && args[0] === 'account') {
      return JSON.stringify({ name: remote.name, state: 'Enabled', id: subscription, tenantId: subscription });
    }
    if (program === 'az' && args[2] === 'blob-service-properties') {
      return JSON.stringify({ isVersioningEnabled: remote.versioning,
        deleteRetentionPolicy: { enabled: true, days: 31 }, containerDeleteRetentionPolicy: { enabled: true, days: 31 } });
    }
    if (program === 'az' && args[1] === 'account') return JSON.stringify({
      id: `/subscriptions/${subscription}/resourceGroups/${config.resource_group_name}/providers/Microsoft.Storage/storageAccounts/${config.storage_account_name}`,
      isHnsEnabled: false, sku: { name: 'Standard_LRS' }, allowSharedKeyAccess: false, allowBlobPublicAccess: false,
      enableHttpsTrafficOnly: true, minimumTlsVersion: 'TLS1_2', tags: { project: 'AzureDataTransformationLab', purpose: 'terraform-state' },
    });
    if (program === 'az' && args[0] === 'rest') return JSON.stringify({ properties: { publicAccess: remote.publicAccess } });
    if (program === 'az' && args[0] === 'lock') return JSON.stringify(remote.locked ? [{
      id: `${args[args.indexOf('--resource') + 1]}/providers/Microsoft.Authorization/locks/state`, level: 'CanNotDelete',
    }] : []);
    if (program === 'az' && args[1] === 'blob') return JSON.stringify(remote.exists);
    if (program === 'terraform' && args.includes('init')) {
      writeFileSync(join(root, '.terraform/terraform.tfstate'), JSON.stringify({ backend: {
        type: 'azurerm', config: { ...remote.config, use_azuread_auth: true },
      } }));
      return '';
    }
    if (program === 'terraform' && args.includes('pull')) return JSON.stringify(remote.state);
    throw new Error('予期しないCLI呼び出し');
  }
  return { root, state, config, remote, calls, run, env: { ARM_SUBSCRIPTION_ID: subscription } };
}

/** 破棄後に保持した、管理対象を持たないstateをfixtureへ追加する。 */
function emptyRebuildFixture(t) {
  const f = fixture(t);
  f.baseline = {
    version: 4,
    lineage: f.state.lineage,
    serial: 11,
    outputs: {},
    resources: [],
  };
  f.baselinePath = join(f.root, 'retained-empty.tfstate');
  writeFileSync(f.baselinePath, JSON.stringify(f.baseline));
  f.remote.exists = true;
  f.remote.state = structuredClone(f.baseline);
  return f;
}

test('remote stateがなければ通常のinitを実行しない', (t) => {
  const f = fixture(t);
  assert.throws(() => runBackend('init', f), /state/);
  assert.ok(f.calls.every(([program]) => program !== 'terraform'));
});

test('移行準備は元stateを退避し、Azureへの書き込みや自動移行を行わない', (t) => {
  const f = fixture(t);
  const result = runBackend('prepare-migration', f);
  assert.deepEqual(JSON.parse(readFileSync(join(result.backupDirectory, 'terraform.tfstate'), 'utf8')), f.state);
  assert.ok(existsSync(join(f.root, 'remote.backend.hcl')));
  assert.ok(f.calls.every(([program]) => program === 'az'));
  assert.ok(!JSON.stringify(result).includes('fake-sensitive-state'));
});

test('既存remote state、空local state、別Subscriptionは移行準備を拒否する', (t) => {
  for (const condition of ['existing', 'empty', 'subscription']) {
    const f = fixture(t);
    if (condition === 'existing') f.remote.exists = true;
    if (condition === 'empty') writeFileSync(join(f.root, 'terraform.tfstate'), '{}');
    if (condition === 'subscription') f.remote.name = 'Personal-Data';
    assert.throws(() => runBackend('prepare-migration', f));
    assert.ok(!existsSync(join(f.root, '.state-backups')));
  }
});

test('Azureの読み取り失敗時も空stateでinitしない', (t) => {
  const f = fixture(t);
  assert.throws(() => runBackend('init', { ...f, run: () => { throw new Error('アクセス拒否'); } }));
  assert.ok(!existsSync(join(f.root, 'remote.backend.hcl')));
});

test('移行後の同一性を確認し、永続化によるserialの一段増加だけを許容する', (t) => {
  const f = fixture(t);
  runBackend('prepare-migration', f);
  f.remote.exists = true;
  assert.deepEqual(runBackend('init', f), { initialized: true });
  assert.deepEqual(runBackend('verify-migration', f), { verified: true, managedResources: 1 });
  f.remote.state = { ...f.state, serial: 9 };
  assert.deepEqual(runBackend('verify-migration', f), { verified: true, managedResources: 1 });
  f.remote.state = { ...f.state, serial: 10 };
  assert.throws(() => runBackend('verify-migration', f), /一致/);
});

test('serialが一段増加していてもlineage・属性・outputsの変更は拒否する', (t) => {
  for (const field of ['lineage', 'resources', 'outputs']) {
    const f = fixture(t);
    runBackend('prepare-migration', f);
    f.remote.exists = true;
    runBackend('init', f);
    const changed = structuredClone(f.state);
    changed.serial += 1;
    if (field === 'lineage') changed.lineage = '33333333-3333-4333-8333-333333333333';
    if (field === 'resources') changed.resources[0].instances[0].attributes.token = 'changed';
    if (field === 'outputs') changed.outputs = { changed: { value: 'changed', type: 'string' } };
    f.remote.state = changed;
    assert.throws(() => runBackend('verify-migration', f), /一致/);
  }
});

test('Blobが存在しても空stateならinitの成功を返さない', (t) => {
  const f = fixture(t);
  f.remote.exists = true;
  f.remote.state = { ...f.state, resources: [] };
  assert.throws(() => runBackend('init', f), /state/);
});

test('公開containerまたは復旧・削除保護の欠けた保存先を拒否する', (t) => {
  for (const condition of ['public', 'versioning', 'lock']) {
    const f = fixture(t);
    if (condition === 'public') f.remote.publicAccess = 'Blob';
    if (condition === 'versioning') f.remote.versioning = false;
    if (condition === 'lock') f.remote.locked = false;
    assert.throws(() => runBackend('prepare-migration', f));
  }
});

test('バックアップ実体が失われた場合は移行成功としない', (t) => {
  const f = fixture(t);
  const { backupDirectory } = runBackend('prepare-migration', f);
  f.remote.exists = true;
  runBackend('init', f);
  rmSync(join(backupDirectory, 'terraform.tfstate'));
  assert.throws(() => runBackend('verify-migration', f));
});

test('cacheに残った長期資格情報と異なるSubscriptionを拒否する', (t) => {
  for (const extra of [{ access_key: 'fake-key' }, { subscription_id: '33333333-3333-4333-8333-333333333333' }]) {
    const f = fixture(t);
    runBackend('prepare-migration', f);
    f.remote.exists = true;
    runBackend('init', f);
    writeFileSync(join(f.root, '.terraform/terraform.tfstate'), JSON.stringify({ backend: {
      type: 'azurerm', config: { ...f.config, use_azuread_auth: true, ...extra },
    } }));
    assert.throws(() => runBackend('verify-migration', f));
  }
});

test('state属性の裸のsubscription_idも照合する', (t) => {
  const f = fixture(t);
  f.state.resources[0].instances[0].attributes.subscription_id = '33333333-3333-4333-8333-333333333333';
  writeFileSync(join(f.root, 'terraform.tfstate'), JSON.stringify(f.state));
  assert.throws(() => runBackend('prepare-migration', f));
});

test('空の保持stateと空のremote stateが一致すれば再構築準備だけを行う', (t) => {
  const f = emptyRebuildFixture(t);
  const localStateBefore = readFileSync(join(f.root, 'terraform.tfstate'), 'utf8');

  const result = runBackend('prepare-rebuild', { ...f, baselinePath: f.baselinePath });

  assert.equal(result.preparedForRebuild, true);
  assert.equal(result.managedResources, 0);
  assert.match(result.backupDirectory, new RegExp(`${f.root}/\\.state-backups/rebuild-`));
  assert.deepEqual(
    JSON.parse(readFileSync(join(result.backupDirectory, 'terraform.tfstate'), 'utf8')),
    f.baseline,
  );
  assert.equal(statSync(join(f.root, '.state-backups')).mode & 0o777, 0o700);
  assert.equal(statSync(result.backupDirectory).mode & 0o777, 0o700);
  assert.equal(statSync(join(result.backupDirectory, 'terraform.tfstate')).mode & 0o777, 0o600);
  assert.equal(readFileSync(join(f.root, 'terraform.tfstate'), 'utf8'), localStateBefore);
  assert.ok(existsSync(join(f.root, 'remote.backend.hcl')));
  const initCall = f.calls.find(([program, ...args]) => program === 'terraform' && args.includes('init'));
  assert.ok(initCall);
  assert.ok(initCall.includes('-reconfigure'));
  assert.ok(!initCall.includes('-migrate-state'));
  assert.ok(f.calls.some(([program, ...args]) => program === 'terraform' && args.includes('pull')));
  assert.ok(f.calls.every(([program, ...args]) => !args.includes('apply') && !args.includes('push')));
});

test('再構築準備は保持stateの存在と空条件をinit前に検証する', (t) => {
  for (const condition of ['missing', 'nonempty', 'bad-lineage', 'bad-serial', 'bad-resources']) {
    const f = emptyRebuildFixture(t);
    if (condition === 'missing') f.baselinePath = join(f.root, 'missing.tfstate');
    if (condition === 'nonempty') f.baseline = f.state;
    if (condition === 'bad-lineage') f.baseline.lineage = 'not-a-lineage';
    if (condition === 'bad-serial') f.baseline.serial = -1;
    if (condition === 'bad-resources') f.baseline.resources = f.state.resources;
    if (condition !== 'missing') writeFileSync(f.baselinePath, JSON.stringify(f.baseline));
    assert.throws(
      () => runBackend('prepare-rebuild', { ...f, baselinePath: f.baselinePath }),
      /state|保持|空/,
    );
    assert.ok(f.calls.every(([program]) => program !== 'terraform'));
    assert.ok(!existsSync(join(f.root, 'remote.backend.hcl')));
  }
});

test('再構築準備はremote Blobがない場合にfallbackせず停止する', (t) => {
  const f = emptyRebuildFixture(t);
  f.remote.exists = false;

  assert.throws(
    () => runBackend('prepare-rebuild', { ...f, baselinePath: f.baselinePath }),
    /remote/,
  );
  assert.ok(f.calls.every(([program]) => program === 'az'));
  assert.ok(!existsSync(join(f.root, 'remote.backend.hcl')));
});

test('再構築準備はremote stateのlineage・serial・resources差分を拒否する', (t) => {
  for (const field of ['lineage', 'serial', 'resources']) {
    const f = emptyRebuildFixture(t);
    if (field === 'lineage') f.remote.state.lineage = '33333333-3333-4333-8333-333333333333';
    if (field === 'serial') f.remote.state.serial += 1;
    if (field === 'resources') f.remote.state.resources = f.state.resources;
    assert.throws(
      () => runBackend('prepare-rebuild', { ...f, baselinePath: f.baselinePath }),
      /state|一致|空/,
    );
  }
});

test('通常のinitはremoteが空でも空stateからの初期化を許可しない', (t) => {
  const f = emptyRebuildFixture(t);

  assert.throws(() => runBackend('init', f), /state/);
});
