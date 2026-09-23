# イベント起点の変換パイプラインを理解するData Factory

Phase 3では、`landing`へのCSV投入をトリガーに、ADF Pipelineが検証Functionを呼び、結果に応じて`validated`・`rejected`・`output`へ振り分ける一連の処理を作ります。

正確な処理フローと業務Reject・システム障害の区別は[アーキテクチャ](../architecture.md)、実行順序と承認条件は[学習計画のPhase 3](../learning-plan.md#phase-3-data-factory-pipeline)に沿って確認します。

## 1. 最初に読むファイル

| ファイル | ここで見ること |
|---|---|
| `infra/terraform/data_factory.tf` | Factory・IR・RBAC・Linked Service・Dataset・Pipeline・Triggerの定義 |
| `infra/terraform/adf/csv_ingestion.activities.json` | PipelineのActivity列と分岐条件 |
| `infra/terraform/adf/transform_orders.dfsql` | Data Flowの変換定義（列改名・型変換・派生列） |
| `infra/terraform/tests/data_factory.tftest.hcl` | Triggerの対象範囲とRBAC scopeの検証 |
| `docs/architecture.md` | 全体フローと障害の扱い |

`data_factory.tf`から読み、どのリソースがどの権限で動くかを押さえてから、activities JSONで順序と分岐を追います。Data Flowスクリプトは最後に読みます。

## 2. Pipelineの流れを追う

```text
Storage Event Trigger（landing/*.csv）
  ↓ folderPath, fileName
SetVariable: relativeDir（landing/を除いた相対フォルダー）
SetVariable: relativePath（relativeDir + fileName）
  ↓
Web: GET landing/<path>?action=getStatus → ETag取得
  ↓
Azure Function: POST /api/validate（filesystem, path, etag）
  ↓
Switch: ValidateCsv.output.status
  ├─ VALID   → Copy landing→validated → ExecuteDataFlow → output
  ├─ INVALID → Copy landing→rejected → Web PUT <path>.validation.json
  └─ その他   → Fail
```

Triggerが渡せるのは`folderPath`と`fileName`だけです。Function契約で必須の`etag`は、Web Activityが`landing/<path>?action=getStatus`（DFS endpointのJSON API）をManaged Identityで呼び、応答の`PathStatus.etag`から組み立てます。`comp=metadata`は応答ヘッダーにETagを返しますが、Web Activityはヘッダーを`output`へ安定して露出しないため、JSON本文を返す`getStatus`を使います。

ETagを検証してからCopyするまでの間に入力が上書きされると、検証した版とコピーした版がずれます。Phase 3ではこの隙間を既知の制約として受け入れ、Phase 6の冪等性で扱います。

## 3. 分岐と障害経路を区別する

Switchは`VALID`・`INVALID`以外の値をFailへ送ります。契約外の応答をINVALID扱いにしないためです。

- HTTP 200・`INVALID` → `rejected`へ原本と`<path>.validation.json`を置き、Pipelineは正常終了
- Functionの4xx/5xx・Timeout → Azure Function Activityが失敗し、Pipelineが失敗
- Copy・Data Flow・Webの失敗 → Pipelineが失敗

Azure Function ActivityはFunction側の応答に関係なく約230秒で打ち切られます。そのためActivityのTimeout（2分）はこの上限より短くしています。

## 4. Terraformで管理する範囲を確認する

Pipeline・Dataset・Data Flow・Triggerは`azurerm_data_factory_*`リソースとしてTerraform管理です。ADF Studioは閲覧用に使い、Git連携は有効にしません。理由は[ADR-0009](../adr/0009-manage-adf-definitions-in-terraform.md)に記録しています。

`activities_json`内のLinked Service・Dataset・Data Flow参照は名前だけなので、Terraformの依存グラフに現れません。`depends_on`で作成順序を明示している箇所を`data_factory.tf`で確認してください。

## 5. planを読む

Azureリソースの作成前に、[学習計画のplan手順](../learning-plan.md#4-planを作り作成内容を読む)に沿って対象Subscription、Resource Group、Data Factory、IR、RBAC、Triggerの対象範囲、費用を確認します。

費用の中心はData Flowの実行です。General 8コア（最小）でクラスター起動を含めて1回あたり数十円規模を見込み、検証は5〜8回に抑えます。plan提示時に公式料金から計算し直します。BudgetとCost AlertはPhase 5のため、この段階では費用を自動停止する仕組みはありません。

## 学習メモ

1. なぜTriggerの`folderPath`・`fileName`だけではFunctionを呼べず、ETag取得のActivityが要るのか。
2. なぜ`If Condition`ではなく`Switch`で分岐し、想定外の値をFailへ送るのか。
3. なぜData Flow用のIRをAutoResolveではなくjapaneast・最小構成で固定するのか。
4. なぜADFのGit連携ではなくTerraformで定義を管理するのか。

回答を書いた後にアーキテクチャとADRを読み直し、実際の定義と一致しているかを確認します。
