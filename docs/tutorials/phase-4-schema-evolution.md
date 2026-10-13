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

2026-10-12に、Debugを1セッション（約9分、24実行）で動かして記録しました。Debugのpreviewは列の型をすべてstringで表示するため、型の違いはpreviewからは読み取れません。

| サンプル | Strict | Tolerant | Drift | Drift＋型推論 |
|---|---|---|---|---|
| `orders_v1.csv` | 成功・3行 | 成功・3行 | 成功・3行 | 成功・3行 |
| `orders_v2.csv`（列追加） | 成功・追加列を出力しない | 成功・追加列を出力しない | 成功・`source_system`を出力 | 成功・`source_system`を出力 |
| `orders_v3.csv`（未知の列2つ） | 成功・追加2列を出力しない | 成功・追加2列を出力しない | 成功・2列を出力 | 成功・2列を出力 |
| `orders_drifted_types.csv`（数値・日時の追加列） | 成功・追加3列を出力しない | 成功・追加3列を出力しない | 成功・3列をstringで出力 | 成功・3列をstringで出力 |
| `orders_missing_required.csv`（`customer_id`なし） | **失敗**（`DF-Executor-InvalidInputColumns`） | 成功・0行 | 成功・0行 | 成功・0行 |
| `orders_amount_type_change.csv`（`"12,800"`、`4500円`） | 成功・0行 | 成功・0行 | 成功・0行 | 成功・0行 |

Trigger経由のPipeline結果は次のとおりです。

| 投入したCSV | 拒否した層 | Pipelineの結果 | 出力先 |
|---|---|---|---|
| `orders_v2.csv` | 拒否なし（Functionが受け入れ、StrictなData Flowが追加列を除いて処理） | 成功 | `validated`と`output` |
| `orders_missing_required.csv` | Function（`missing required column: customer_id`） | 成功 | `rejected`に原本と検証結果JSON |
| `orders_amount_type_change.csv` | Function（`amount must be a plain decimal`が2行） | 成功 | `rejected`に原本と検証結果JSON |

## 4. 分かったこと

- **Strictは追加列では失敗しません。** `validateSchema: true`が失敗させるのは、宣言した列が入力にないときだけでした。追加列はStrictでもTolerantでも出力に含まれず、「Strictは宣言と異なる入力で失敗する」という予想は、列の欠落にだけ当てはまりました。そのため、Functionが受け入れる追加列入りのCSVが、Data Flowでシステム障害になる心配はありません。
- **Tolerantは問題を隠します。** 必須列が欠けても失敗せず、0行の成功になります。`amount`が数値でない場合は、Strictでも変換結果がnullになり、行が静かに除かれて0行の成功になります。Data Flowだけでは、入力の不備と「該当する行がない」を区別できません。
- **Driftは列を通すだけです。** 宣言外の列は、出力の列名ルールを置いた場合にだけstringのまま出力に残ります。`Infer drifted column types`を加えても、previewでは出力に違いが出ませんでした。推論された型を確かめるには、型を持つsinkの出力か、スキーマを確認できる別の手段が必要です。
- **推論と受け入れは別の判断です。** 列を推論できても、その列を出力に含めるか、下流が受け取れるかは、列名のルールとsinkの設定が決めます。必須列の欠落と型の不正を拒否しているのは、Data Flowではなく、Pipeline上で先に動く入力検証Functionです。Data Flowを緩めても厳しくしても、この2つはFunctionが止めます。

## 5. 確かめられなかったこと

`Infer drifted column types`が推論した型は、今回の方法では確かめられていません。Debugのpreviewは型をすべてstringで表示するため、`df_schema_drift`と`df_schema_drift_infer`の違いが読み取れませんでした。型を保持するsinkへ書き出して確かめる方法は未実施です。このフラグで出力の型が変わったかどうかは、この比較からは判断できません。

## 理解度チェック

1. 必須列の欠落と`amount`の型変更は、Pipeline上のどの層で拒否されるか。Data Flowの設定を変えると、その結果は変わるか。（1節、4節）
2. `validateSchema: true`のStrictは、どんな入力で失敗し、どんな入力では失敗しないか。（3節、4節）
3. Tolerantで必須列が欠けたCSVが「0行の成功」になることは、なぜ問題か。（4節）
4. `Allow schema drift`を有効にしても、宣言外の列が出力に残らないのはどんな場合か。（2節）
5. スキーマを推論できることと、変化を受け入れることが別の判断だと言えるのはなぜか。（4節）

答えを書いたら、該当する節と[学習計画のPhase 4](../learning-plan.md#phase-4-schema-evolution)を読み直し、比較結果と一致しているかを確かめます。
