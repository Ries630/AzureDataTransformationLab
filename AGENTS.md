# プロジェクト固有の指示

## 正となる文書

- 目的、前提、制約、完成条件は [docs/project-brief.md](docs/project-brief.md) を参照する。
- サービス構成、処理責務、異常系は [docs/architecture.md](docs/architecture.md) を参照する。
- 実装順序、検証項目、利用ツールは [docs/learning-plan.md](docs/learning-plan.md) を参照する。
- `docs/archive/` は履歴であり、現在の仕様として扱わない。

## 作業上の制約

- 未確定のAWS案件情報を推測で確定事項にしない。
- 一度に複数フェーズを実装せず、承認されたフェーズだけを進める。
- Azureリソースを作成する前に`terraform plan`を提示し、明示的な承認を得る。
- 高額なSKUや常時稼働リソースを追加しない。
- Purview、Databricks、Private Endpointは、要件が追加されるまで導入しない。
- Python依存管理とAzure Functionsへの配置方法は、[Phase 2](docs/learning-plan.md#phase-2-azure-functionsによる入力検証)を正とする。

## Codexレビュー指摘への応答

- Codex のレビューコメントへの返信で `@codex` がメンションされた場合、明示的な修正依頼が
  なければ、コードを変更せずレビュー指摘への対応状況を再判定する
- コードが修正されている場合は、現在の PR head を確認し、指摘した問題が解消されたかを
  判定する
- 説明だけが返信されている場合は、コード・Issue・リポジトリの規範と照合し、その説明が
  妥当かを判定する
- 結論は `解消` / `未解消` / `説明妥当` / `説明不十分` のいずれかで、日本語で根拠を添える
- 判定結果と根拠は同じレビュースレッドへ返信せず、Codex GitHub 連携が表示するタスクの
  最終報告に記載する
- `解消` または `説明妥当` と判定した場合だけ Resolve し、`未解消` または `説明不十分` の
  場合は Resolve しない

## Code Review Rules

- レビューコメントは日本語で記載する
