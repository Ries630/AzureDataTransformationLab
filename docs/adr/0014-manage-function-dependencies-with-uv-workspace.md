# ADR-0014: Function・Lambdaの依存関係をuv workspaceで管理する

- ステータス: 提案
- 日付: 2026-10-26
- 関連: [ADR-0005](0005-package-functions-with-pep723-and-uv.md)

## 背景

[ADR-0005](0005-package-functions-with-pep723-and-uv.md)では、Azure validatorの依存関係を`function_app.py`のPEP 723メタデータと隣接するロックで管理した。その後、AWS Lambdaの`handler.py`とテスト用の`scripts/aws/test_pipeline.py`にも、同じ形式の別々のロックが増えた。

現在の構成では、次の負担がある。

- `validation.py`をAzureとAWSで共有しているのに、依存関係のロックは入口のファイルごとに分かれている。そのため、同じ依存の版がファイルごとにずれる。
- `test_pipeline.py`は、Lambdaと同じBoto3を使うために、Lambdaとは別のロックを持つ必要がある。
- Ruffやtyなどの開発ツールの版を、依存関係と同じ場所で固定できない。
- 型チェッカーに依存環境を渡すとき、スクリプトごとの環境を個別に探す必要がある。

## 決定

ルートの`pyproject.toml`をuv workspaceとし、依存関係を1つの`uv.lock`で固定する。

- workspaceのメンバーは`functions/validator`（`validator`）と`functions/aws`（`aws-lambda`）とする。どちらも`[tool.uv] package = false`とし、パッケージとしてはビルドしない。
- 開発ツール（Ruff、ty）は、ルートの`[dependency-groups]`の`dev`で固定する。lint設定は引き続き`ruff.toml`に置く。
- 配置用の依存は`uv export --locked --package <メンバー> --no-dev --no-emit-workspace`で書き出す。書き出した結果は、ハッシュ検証とwheel限定でインストールする。生成処理と配置形式（`.python_packages`、Lambda ZIP）、manifestの検証はADR-0005のまま維持し、manifestの`lock_sha256`は`uv.lock`を指す。
- 次のものは、新しい規則でいう「単体で動くスクリプト」にあたるため、PEP 723で管理する。
  - Glue 5.1と同じPython 3.11で動かすSpark検査（`scripts/aws/test_spark.py`）。workspaceは全メンバーで1つのPythonの版を共有するので、3.14のメンバーとは一緒にできない。
  - リポジトリなしで動かす配布物検査など、`scripts/`の下の依存のないツール。
- `validation.py`は、パッケージには分けずに今の場所に置く。AzureとAWSの生成処理が、それぞれファイルとして同梱する方式を維持する。

具体的な実行手順は[学習計画のPhase 2](../learning-plan.md#phase-2-azure-functionsによる入力検証)を参照する。

## 検討した代替

PEP 723を維持し、ロックをファイルごとに置き続ける方式は、変更が要らない。しかし、上の負担が残るため採用しない。

`validation.py`を独立したworkspaceメンバー（ライブラリ）にする方式は、共有の境界が明確になる。一方、`function_app.py`と`handler.py`のimport、両方の生成処理、AWS転送物の構成まで変える必要があり、依存管理の移行とは別の変更になるため、今回は採用しない。

メンバーごとに別々の`pyproject.toml`と`uv.lock`を置く方式は、版の衝突が起きない。しかし、共通の推移的依存（`urllib3`など）が再びずれるため採用しない。

## 受け入れた代償

1つのロックを共有するため、AzureとAWSで共通する推移的依存は同じ版になる。移行時に、Azure validatorの`urllib3`はAWS側に合わせて2.7.0から2.8.0になった。ほかの依存の版は、移行前のロックと同じである。

Azure側の依存を更新しても`uv.lock`のSHA-256が変わるため、AWSのLambda ZIPと転送物も作り直しの対象になる。また、AWS転送物には、workspaceの解決に必要な`pyproject.toml`、両メンバーの`pyproject.toml`、`uv.lock`を含める。

## 再評価の条件

- AzureとAWSで、共通の依存に異なる版が必要になった場合
- Azure FunctionsまたはLambdaのPythonの版が、互いに異なる版へ移る場合
- `validation.py`以外にも、共有するコードが増えた場合

## 根拠

- [uv: Using workspaces](https://docs.astral.sh/uv/concepts/projects/workspaces/)
- [uv: Dependency groups](https://docs.astral.sh/uv/concepts/projects/dependencies/#dependency-groups)
- [PEP 735: Dependency Groups in pyproject.toml](https://peps.python.org/pep-0735/)
