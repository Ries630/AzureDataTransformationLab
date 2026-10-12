# Phase 4: 列と型が変わったCSVを、どこで受け入れ、どこで拒否するか

Phase 3のPipelineは、決まった5列のCSVを前提にしています。実際の連携元では、列が増える、必須の列がなくなる、数値だった値に記号が混ざる、といった変化が起こります。Phase 4では、こうした変化に対してFunctionとMapping Data Flowがそれぞれ何をするかを比べ、スキーマを推論できることと、変化を受け入れることが別の判断である理由を確かめます。

実行手順と承認条件は[学習計画のPhase 4](../learning-plan.md#phase-4-schema-evolution)、Functionの検証規則は[アーキテクチャ](../architecture.md#azure-functionsの責務)を正とします。

## 1. 2つの層が受け持つ判断

Pipelineでは、Functionが先にCSVを検証し、受け入れたものだけがData Flowへ進みます。

| 層 | 見ているもの | 列追加 | 必須列の欠落 | `amount`の型変更 |
|---|---|---|---|---|
| Function | ヘッダーと各セルの値 | 受け入れる | 拒否する（業務Reject） | 拒否する（業務Reject） |
| Data Flow | sourceで宣言した列と、Data Flowの設定 | 設定で変わる | Functionが止めるため届かない | Functionが止めるため届かない |

Functionの判定は`tests/validator/test_schema_evolution_samples.py`で固定しています。Pipeline上でData Flowの設定差が表れるのは列追加だけです。必須列の欠落と型変更をData Flowがどう扱うかは、Functionを通さずにDebugで直接確かめます。

## 2. 比べる4つの設定

| Data Flow | sourceの設定 | 出力の列 | 予想 |
|---|---|---|---|
| `df_transform_orders`（Strict） | `allowSchemaDrift: false`、`validateSchema: true` | 宣言した6列 | 宣言と異なる入力で失敗する |
| `df_schema_tolerant` | `allowSchemaDrift: false`、`validateSchema: false` | 宣言した6列 | 宣言外の列を無視して成功する |
| `df_schema_drift` | `allowSchemaDrift: true` | 宣言した6列＋宣言外の列 | 宣言外の列をstringのまま出力する |
| `df_schema_drift_infer` | 上記＋`inferDriftedColumnTypes: true` | 同上 | 宣言外の列の型を値から推論する |

`Allow schema drift`を有効にしても、sinkで出力列を固定すると宣言外の列は出力されません。Drift系の2つは、変換の最後に`select`の列名ルール（元の列名3つ以外をすべて残す）を置き、sinkでも`allowSchemaDrift: true`にして、宣言外の列を出力まで通しています。

予想の列は比較前の仮説です。実際の挙動は次の比較結果で確かめます。

## 3. 比較結果

Debugの結果は`Data preview`と`Inspect`で記録します。各セルには、失敗か成功か、出力された列（宣言外の列の扱い）、推論された型、行数を書きます。

| サンプル | Strict | Tolerant | Drift | Drift＋型推論 |
|---|---|---|---|---|
| `orders_v1.csv` | 未記録 | 未記録 | 未記録 | 未記録 |
| `orders_v2.csv`（列追加） | 未記録 | 未記録 | 未記録 | 未記録 |
| `orders_v3.csv`（未知の列2つ） | 未記録 | 未記録 | 未記録 | 未記録 |
| `orders_drifted_types.csv`（数値・日時の追加列） | 未記録 | 未記録 | 未記録 | 未記録 |
| `orders_missing_required.csv`（`customer_id`なし） | 未記録 | 未記録 | 未記録 | 未記録 |
| `orders_amount_type_change.csv`（`"12,800"`、`4500円`） | 未記録 | 未記録 | 未記録 | 未記録 |

Trigger経由のPipeline結果は次の表に記録します。

| 投入したCSV | 拒否した層 | Pipelineの結果 | 出力先 |
|---|---|---|---|
| `orders_v2.csv` | 未記録 | 未記録 | 未記録 |
| `orders_missing_required.csv` | 未記録 | 未記録 | 未記録 |
| `orders_amount_type_change.csv` | 未記録 | 未記録 | 未記録 |

## 4. 推論と受け入れは別の判断

`Infer drifted column types`は、届いた値から型を推測する機能です。推測できたからといって、その列を出力に含めてよいか、下流が新しい列や型を扱えるかは決まりません。受け入れるかどうかは、Functionの検証規則とData Flowの設定という、別々の場所で決めています。

この節は、比較結果をもとに、どの変化をどの層で受け入れ、どの変化を拒否したかを書き足します。
