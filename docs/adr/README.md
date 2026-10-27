# Architecture Decision Records

コードから理由を読み取れない長期的な設計判断を、判断した時点の記録として残す。

## 運用

1. 最初の ADR が必要になった時点でこのディレクトリを作る。
2. Issue で判断し、ADR を実装する PR に含める。
3. ファイル名は `NNNN-kebab-case-summary.md` とし、連番にする。
4. 判断が変わったら新しい ADR で置換する。古い判断の理由を上書きしない。
5. 用語の定義は `CONTEXT.md`、ADR の作成基準と書式は `adr` skill を正とする。

## 一覧

| # | 決定 | ステータス |
|---|---|---|
| [0001](0001-isolate-learning-subscription.md) | 学習用リソースを専用Subscriptionへ分離する | 承認済み |
| [0002](0002-share-state-in-dedicated-storage.md) | 学習用stateを専用Storageで共有する | 承認済み |
| [0003](0003-use-scoped-oidc-for-pr-plans.md) | PRのplanを専用Identityと承認付きEnvironmentで実行する | 承認済み |
| [0004](0004-separate-function-host-storage.md) | Azure FunctionsのホストStorageと入力Storageを分離する | 承認済み |
| [0005](0005-package-functions-with-pep723-and-uv.md) | PEP 723の依存関係をuvでAzure Functions用にパッケージする | 承認済み |
| [0006](0006-scoped-function-refresh-permissions.md) | CIのFunctions設定読取権限をApp単体へ限定する | 承認済み |
| [0007](0007-set-flex-max-instance-count.md) | HTTP Functionの最大インスタンス数を40に設定する | 承認済み |
| [0008](0008-adf-function-auth-with-host-key.md) | ADFからFunctionへの呼び出しにFunctionキーを使う | 承認済み |
| [0009](0009-manage-adf-definitions-in-terraform.md) | ADFのPipeline・Dataset・Data FlowをTerraformで管理する | 承認済み |
| [0010](0010-require-function-applied-before-data-factory.md) | Data Factory有効化の前にFunction Appを適用済みにする | 承認済み |
| [0011](0011-coordinate-input-attempts-in-dynamodb.md) | DynamoDBで入力世代と処理attemptを制御する | 承認済み |
| [0012](0012-use-glue-spark-for-schema-evolution.md) | スキーマ変化の比較にGlue Sparkを使う | 承認済み |
| [0013](0013-track-input-generations-in-table-storage.md) | 入力世代の処理状態をTable Storageの条件付き更新で管理する | 提案 |
| [0014](0014-manage-function-dependencies-with-uv-workspace.md) | Function・Lambdaの依存関係をuv workspaceで管理する | 提案 |

## テンプレート

[`template.md`](template.md) をコピーして使う。
