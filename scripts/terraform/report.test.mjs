import assert from 'node:assert/strict';
import { test } from 'node:test';
import { prepareReport, renderReport } from './report.mjs';

const subscription = '11111111-1111-4111-8111-111111111111';
const principal = '22222222-2222-4222-8222-222222222222';

/** Azureへの接続を必要としない、既知のplanを作る。 */
function fixture() {
  return {
    format_version: '1.2',
    terraform_version: '1.16.0',
    variables: { subscription_id: { value: subscription } },
    prior_state: { values: { root_module: { resources: [{
      address: 'data.azurerm_subscription.current',
      mode: 'data',
      values: { display_name: 'Personal-Sandbox', subscription_id: subscription },
    }] } } },
    resource_changes: [{
      address: 'azurerm_resource_group.lab',
      mode: 'managed',
      type: 'azurerm_resource_group',
      name: 'lab',
      provider_name: 'registry.terraform.io/hashicorp/azurerm',
      change: {
        actions: ['create'],
        before: null,
        after: { name: 'rg-example', tags: { principal, token: 'fixture-secret-123' } },
        after_sensitive: { tags: { token: true } },
        after_unknown: { id: true },
      },
    }],
  };
}

test('追加件数を保ち、sensitive値と環境IDをrendererへ渡さない', () => {
  const report = prepareReport(fixture(), subscription);
  assert.deepEqual(report.counts, { add: 1, change: 0, destroy: 0 });
  const serialized = JSON.stringify(report.plan);
  for (const value of [subscription, principal, 'fixture-secret-123']) {
    assert.ok(!serialized.includes(value));
  }
  assert.equal(report.plan.resource_changes[0].change.after.name, 'rg-example');
});

test('更新・削除・置換の件数をTerraformの操作として数える', () => {
  const plan = fixture();
  const resource = plan.resource_changes[0];
  plan.resource_changes = [
    { ...resource, change: { ...resource.change, actions: ['update'] } },
    { ...resource, change: { ...resource.change, actions: ['delete'] } },
    { ...resource, change: { ...resource.change, actions: ['delete', 'create'] } },
  ];
  assert.deepEqual(prepareReport(plan, subscription).counts, { add: 1, change: 1, destroy: 2 });
});

test('Personal-Dataや別SubscriptionのResource IDを含むplanを拒否する', () => {
  const wrongName = fixture();
  wrongName.prior_state.values.root_module.resources[0].values.display_name = 'Personal-Data';
  assert.throws(() => prepareReport(wrongName, subscription));
  const wrongResource = fixture();
  wrongResource.resource_changes[0].change.after.id =
    `/subscriptions/${principal}/resourceGroups/rg-example`;
  assert.throws(() => prepareReport(wrongResource, subscription));
  assert.throws(() => prepareReport(fixture(), principal));
});

test('planのoutputsとstateのsensitive値も表示用コピーから除去する', () => {
  const plan = fixture();
  plan.output_changes = {
    token: { actions: ['create'], after: 'output-secret', after_sensitive: true },
  };
  plan.planned_values = { outputs: { token: { value: 'output-secret', sensitive: true } } };
  plan.prior_state.values.root_module.resources.push({
    values: { nested: [{ password: 'state-secret' }] },
    sensitive_values: { nested: [{ password: true }] },
  });
  const result = JSON.stringify(prepareReport(plan, subscription).plan);
  assert.ok(!result.includes('output-secret'));
  assert.ok(!result.includes('state-secret'));
});

test('refreshで検出されたdriftの古いsensitive値も除去する', () => {
  const plan = fixture();
  plan.resource_drift = [{
    address: 'azurerm_resource_group.lab',
    change: {
      actions: ['update'], before: { token: 'old-drift-secret' }, after: { token: 'new-drift-secret' },
      before_sensitive: { token: true }, after_sensitive: { token: true },
    },
  }];
  const body = JSON.stringify(prepareReport(plan, subscription).plan);
  assert.ok(!body.includes('old-drift-secret'));
  assert.ok(!body.includes('new-drift-secret'));
});

test('未完成のplanや不明な操作を成功として公開しない', () => {
  const plan = fixture();
  plan.errored = true;
  assert.throws(() => prepareReport(plan, subscription));
  delete plan.errored;
  plan.resource_changes[0].change.actions = ['forget'];
  assert.throws(() => prepareReport(plan, subscription));
});

test('固定版rendererでGitHub向けMarkdownを生成できる', {
  skip: !process.env.TFPLAN2MD_PATH && 'TFPLAN2MD_PATHを指定すると実rendererを検証する',
}, () => {
  const body = renderReport(fixture(), subscription, process.env.TFPLAN2MD_PATH);
  assert.ok(body.startsWith('<!-- terraform-plan:infra/terraform -->'));
  assert.match(body, /add: 1 \/ change: 0 \/ destroy: 0/);
  assert.match(body, /azurerm_resource_group/);
  assert.match(body, /<details\b[^>]*>/);
  assert.doesNotMatch(body, /<details\b[^>]*\sopen(?:\s|=|>)/);
  for (const value of [subscription, principal, 'fixture-secret-123']) {
    assert.ok(!body.includes(value));
  }
});
