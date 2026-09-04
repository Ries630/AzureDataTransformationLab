import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

const uuidPattern = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi;

/** 子moduleを含むTerraformのリソースを列挙する。 */
function resourcesIn(module) {
  return [
    ...(module?.resources ?? []),
    ...(module?.child_modules ?? []).flatMap(resourcesIn),
  ];
}

/** moduleへ渡されたaliasも、元のProvider設定へ結び付ける。 */
function configuredResourcesIn(module) {
  return [
    ...(module?.resources ?? []),
    ...Object.values(module?.module_calls ?? {}).flatMap((call) => configuredResourcesIn(call.module)),
  ];
}

/** IDが未確定のリソースも、使用するProviderのSubscriptionを確認する。 */
function validateProviderSubscriptions(plan, expectedSubscription) {
  const providers = plan.configuration?.provider_config;
  if (!providers || !plan.configuration?.root_module) {
    throw new Error('ProviderのSubscriptionを確認できません。');
  }
  const configured = configuredResourcesIn(plan.configuration.root_module);
  for (const resource of configured) {
    if (!providers[resource.provider_config_key]) {
      throw new Error('ProviderのSubscriptionを確認できません。');
    }
  }
  for (const key of new Set(configured.map((resource) => resource.provider_config_key))) {
    const provider = providers[key];
    if (provider.full_name !== 'registry.terraform.io/hashicorp/azurerm') continue;
    const expression = provider.expressions?.subscription_id;
    let subscriptionIds = [];
    if (expression && Object.hasOwn(expression, 'constant_value')) {
      subscriptionIds = [expression.constant_value];
    } else if (expression) {
      // referencesは式の依存先であり、評価結果ではない。同じProviderの実取得値を使う。
      const clients = configured.filter((resource) => resource.provider_config_key === key &&
        resource.mode === 'data' && resource.type === 'azurerm_client_config');
      const addresses = new Set(clients.map((resource) => resource.address));
      const deferred = plan.resource_changes.some((resource) =>
        addresses.has(resource.address) && resource.change?.actions?.includes('read'));
      if (!deferred) {
        // plan時にrefresh済みのdataはprior_stateにだけ含まれることがある。
        subscriptionIds = [
          ...resourcesIn(plan.prior_state?.values?.root_module),
          ...resourcesIn(plan.planned_values?.root_module),
        ].filter((resource) => addresses.has(resource.address) && resource.mode === 'data' &&
          resource.type === 'azurerm_client_config').map((resource) => resource.values?.subscription_id);
      }
    }
    if (subscriptionIds.length === 0 || subscriptionIds.some((id) =>
      typeof id !== 'string' || id.toLowerCase() !== expectedSubscription.toLowerCase())) {
      throw new Error('ProviderのSubscriptionが一致しないか確認できません。');
    }
  }
}

/** 表示処理とは独立して、planの実行対象と完了状態を検証する。 */
export function validatePlan(plan, expectedSubscription) {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(expectedSubscription ?? '') ||
      plan.variables?.subscription_id?.value?.toLowerCase() !== expectedSubscription.toLowerCase()) {
    throw new Error('対象Subscriptionが一致しません。');
  }
  if (plan.errored || plan.complete === false || !Array.isArray(plan.resource_changes)) {
    throw new Error('完了したplanが必要です。');
  }
  validateProviderSubscriptions(plan, expectedSubscription);
  const subscriptions = [
    ...resourcesIn(plan.prior_state?.values?.root_module),
    ...resourcesIn(plan.planned_values?.root_module),
  ].filter((resource) => resource.address === 'data.azurerm_subscription.current');
  if (subscriptions.length === 0 || subscriptions.some(({ values }) =>
    values?.display_name !== 'Personal-Sandbox' ||
    values?.subscription_id?.toLowerCase() !== expectedSubscription.toLowerCase())) {
    throw new Error('Personal-Sandboxの取得結果を確認できません。');
  }
  // データソース、state、変更前後も含め、別Subscriptionの参照を許可しない。
  mapStrings(plan, (value) => {
    for (const match of value.matchAll(/\/subscriptions\/([^/\s"?]+)/gi)) {
      if (match[1].toLowerCase() !== expectedSubscription.toLowerCase()) {
        throw new Error('対象外Subscriptionへの参照があります。');
      }
    }
    return value;
  });
  const supportedActions = new Set(['no-op', 'create', 'update', 'delete', 'delete,create', 'create,delete']);
  for (const resource of plan.resource_changes) {
    if (resource.mode === 'managed' &&
        (!supportedActions.has(resource.change?.actions?.join(',')) ||
         resource.provider_name !== 'registry.terraform.io/hashicorp/azurerm')) {
      throw new Error('未対応のリソースまたは操作が含まれています。');
    }
  }
}

/** sensitiveとして指定された値を、rendererへ渡す前に除去する。 */
function maskSensitive(value, mask, secrets) {
  if (mask === true) {
    collectStrings(value, secrets);
    return value === null ? null : '(sensitive)';
  }
  if (Array.isArray(value)) {
    return value.map((item, index) => maskSensitive(item, mask?.[index], secrets));
  }
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [
      key, maskSensitive(item, mask?.[key], secrets),
    ]));
  }
  return value;
}

/** 他の属性に同じ機密値が複製された場合も除去できるように収集する。 */
function collectStrings(value, secrets) {
  if (typeof value === 'string' && value.length > 0) secrets.add(value);
  else if (value && typeof value === 'object') {
    for (const item of Object.values(value)) collectStrings(item, secrets);
  }
}

/** 同じIDを同じ架空UUIDへ置換し、rendererによるAzure IDの解釈を維持する。 */
function pseudonymizeId(value) {
  const digest = createHash('sha256').update(value.toLowerCase()).digest('hex');
  return `00000000-0000-4000-8000-${digest.slice(0, 12)}`;
}

/** 配列・オブジェクトのキーも含めて、公開用文字列へ変換する。 */
function mapStrings(value, transform) {
  if (typeof value === 'string') return transform(value);
  if (Array.isArray(value)) return value.map((item) => mapStrings(item, transform));
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [
      transform(key), mapStrings(item, transform),
    ]));
  }
  return value;
}

/** planの件数を数え、機密値と実環境IDを持たない表示専用コピーを返す。 */
export function prepareReport(input, expectedSubscription) {
  validatePlan(input, expectedSubscription);
  const plan = structuredClone(input);
  const counts = { add: 0, change: 0, destroy: 0 };
  const secrets = new Set();
  for (const resource of plan.resource_changes ?? []) {
    const change = resource.change;
    if (resource.mode === 'managed') {
      if (change.actions.includes('create')) counts.add += 1;
      if (change.actions.includes('update')) counts.change += 1;
      if (change.actions.includes('delete')) counts.destroy += 1;
    }
  }
  for (const resource of [...plan.resource_changes, ...(plan.resource_drift ?? [])]) {
    const change = resource.change;
    change.before = maskSensitive(change.before, change.before_sensitive, secrets);
    change.after = maskSensitive(change.after, change.after_sensitive, secrets);
  }
  for (const change of Object.values(plan.output_changes ?? {})) {
    change.before = maskSensitive(change.before, change.before_sensitive, secrets);
    change.after = maskSensitive(change.after, change.after_sensitive, secrets);
  }
  for (const values of [plan.prior_state?.values, plan.planned_values]) {
    for (const resource of resourcesIn(values?.root_module)) {
      resource.values = maskSensitive(resource.values, resource.sensitive_values, secrets);
    }
    for (const output of Object.values(values?.outputs ?? {})) {
      output.value = maskSensitive(output.value, output.sensitive, secrets);
    }
  }
  for (const [key, metadata] of Object.entries(plan.configuration?.root_module?.variables ?? {})) {
    if (metadata.sensitive && plan.variables?.[key]) {
      plan.variables[key].value = maskSensitive(plan.variables[key].value, true, secrets);
    }
  }
  const privateValues = new Set(secrets);
  mapStrings(input, (value) => {
    for (const match of value.matchAll(uuidPattern)) privateValues.add(match[0]);
    return value;
  });
  const orderedSecrets = [...secrets].sort((left, right) => right.length - left.length);
  const sanitized = mapStrings(plan, (text) => {
    for (const secret of orderedSecrets) text = text.split(secret).join('(sensitive)');
    return text.replace(uuidPattern, pseudonymizeId);
  });
  /** rendererの出力に元の機密値・IDが再出現していないことを確認する。 */
  function assertSafe(text) {
    for (const value of privateValues) {
      if (text.includes(value) || text.includes(encodeURIComponent(value))) {
        throw new Error('公開用レポートに非公開の値が残っています。');
      }
    }
  }
  assertSafe(JSON.stringify(sanitized));
  return { counts, plan: sanitized, assertSafe };
}

/** 固定版のrendererを起動し、公開可能なMarkdownだけを返す。 */
export function renderReport(input, expectedSubscription, renderer = 'tfplan2md') {
  const { counts, plan, assertSafe } = prepareReport(input, expectedSubscription);
  const result = spawnSync(renderer, [
    '--render-target', 'github', '--details', 'closed', '--hide-metadata',
  ], { input: JSON.stringify(plan), encoding: 'utf8', maxBuffer: 4 * 1024 * 1024, timeout: 60_000 });
  if (result.error || result.status !== 0 || !result.stdout.trim()) {
    // rendererの診断には入力の一部が含まれ得るため、公開ログへ転記しない。
    throw new Error('tfplan2mdによる変換に失敗しました。');
  }
  const body = [
    '<!-- terraform-plan:infra/terraform -->',
    '## Terraform plan',
    '',
    `**add: ${counts.add} / change: ${counts.change} / destroy: ${counts.destroy}**`,
    '',
    '環境IDは架空のIDへ置換しています。この表示は適用承認ではありません。',
    '',
    result.stdout.trim(),
    '',
    '🤖 Generated with [Codex](https://developers.openai.com/codex)',
    '',
  ].join('\n');
  assertSafe(body);
  if (Buffer.byteLength(body, 'utf8') > 60_000) {
    throw new Error('PRコメントの上限を超えるため、公開を中止しました。');
  }
  return body;
}

/** ローカルのplan JSONからMarkdownを作り、成功時だけ出力を置き換える。 */
function main() {
  const [inputPath, outputPath] = process.argv.slice(2);
  if (!inputPath || !outputPath || !process.env.ARM_SUBSCRIPTION_ID) {
    throw new Error('plan JSON、出力先、ARM_SUBSCRIPTION_IDを指定してください。');
  }
  const body = renderReport(
    JSON.parse(readFileSync(inputPath, 'utf8')),
    process.env.ARM_SUBSCRIPTION_ID,
    process.env.TFPLAN2MD_PATH || 'tfplan2md',
  );
  const temporaryPath = `${outputPath}.${process.pid}.tmp`;
  try {
    writeFileSync(temporaryPath, body, { mode: 0o600, flag: 'wx' });
    renameSync(temporaryPath, outputPath);
  } finally {
    rmSync(temporaryPath, { force: true });
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    main();
  } catch {
    // JSON構文エラーも入力断片を含むため、機密性のない固定メッセージを返す。
    console.error('planの検証またはレポート生成に失敗しました。公開を中止します。');
    process.exitCode = 1;
  }
}
