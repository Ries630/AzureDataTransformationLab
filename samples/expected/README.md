# Azure Phase 3・4との比較用期待値

このディレクトリは、架空の固定入力、[入力検証コード](../../functions/validator/validation.py)、[変換式](../../infra/terraform/adf/transform_orders.dfsql)、[Drift変換式](../../infra/terraform/adf/schema-evolution/drift.dfsql)からローカルで派生した期待値を置く。**実Azureの実行結果を採取したデータではない。** 検証JSONは`validate_csv`を`uv run`で実行して生成し、変換CSVは変換式の列名変更、Decimal変換、税込計算を固定入力に適用して作成した。

入力・変換と比較の規則の正は[比較基準](../../docs/architecture.md#比較基準)とする。Azureで観測したPhase 4の挙動は[比較結果](../../docs/tutorials/phase-4-schema-evolution.md#3-比較結果)を参照する。

## 固定入力との対応

同じbasenameの検証JSONは`validation/`、正常変換CSVは`transformed/standard/`に置く。追加列を通すDriftの期待値は`transformed/drift/`に置く。

| 入力 | 検証結果 | 入力行数 | 正常変換行数 | Drift追加列 |
|---|---|---:|---:|---|
| [orders_v1.csv](../valid/orders_v1.csv) | VALID | 3 | 3 | なし（standardと同じ） |
| [orders_invalid.csv](../invalid/orders_invalid.csv) | INVALID・5エラー | 3 | 対象外 | 対象外 |
| [orders_v2.csv](../schema-evolution/orders_v2.csv) | VALID | 1 | 1 | `source_system` |
| [orders_v3.csv](../schema-evolution/orders_v3.csv) | VALID | 1 | 1 | `source_system`、`promotion_code` |
| [orders_drifted_types.csv](../schema-evolution/orders_drifted_types.csv) | VALID | 2 | 2 | `quantity`、`discount_rate`、`shipped_at` |
| [orders_missing_required.csv](../schema-evolution/orders_missing_required.csv) | INVALID・1エラー | 2 | 対象外 | 対象外 |
| [orders_amount_type_change.csv](../schema-evolution/orders_amount_type_change.csv) | INVALID・2エラー | 2 | 対象外 | 対象外 |

`standard`はPhase 3の`df_transform_orders`とPhase 4のStrict・Tolerantを通る正常入力に対応する。`drift`は追加列を残す変換式に対応する。INVALID入力はPipelineで変換へ進まないため、空の変換CSVを作らない。Functionを通さないDebug実行はこの期待値の対象外とする。

## このデータで比較できること

検証JSONは公開APIの`status`、`errorCount`、各エラーの`row`・`column`・`message`を比較する。CSVは列名と各列の値、行数を比較する。行順に意味を持たせず、重複行の件数を保つ多重集合として照合する。入力行数と正常変換行数が等しいことも確認する。サービス固有の実行ID・出力ファイル名は比較対象に含めない。

金額のCSV表記は`amount`を4桁、`taxIncludedAmount`を5桁の小数で固定した。これはDecimalとして計算した値を明示するためで、Azure sinkの文字列表記を再現したものではない。比較時はDecimalとして読む。浮動小数点への変換や許容誤差による照合は使わない。

現在の固定入力の日時はすべてタイムゾーンと小数秒を省略している。期待CSVも同じ日時を保持し、UTCへの変換やローカルタイムゾーンの補完をしていない。zone付き日時の正規化や小数秒の挙動は、この固定データだけでは確かめられない。

追加列を残すDriftのCSVでは、未知列の入力文字列をそのまま保持する。`inferDriftedColumnTypes`による内部型推論を確認した証跡ではない。CSVの値だけでは推論された型を確定できないため、型の検証には別途型情報を持つ出力が必要になる。

## 未網羅の比較

固定入力には小数部4桁・整数部14桁の境界、zone付き日時、ミリ秒の境界、同一入力世代の重複配送や途中失敗後の再実行が含まれていない。これらをこの期待値の比較で検証済みとして扱わない。入力検証の境界ケースは[既存の検証テスト](../../tests/validator/)を参照し、AWS実機での重複・再実行は[AWSの学習計画](../../docs/aws-learning-plan.md)に沿って確認する。

期待値を更新する場合は、対応する入力・検証コード・変換式との差分を確認してから再生成し、行数とDecimalの値を照合する。実環境の出力を置く場合は、この派生値と区別した採取元・採取日・入力世代を記録する。
