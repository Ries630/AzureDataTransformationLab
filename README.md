# Azure Data Transformation Lab

仕事で予定されているAWSベースのデータ変換層を理解するため、Azure上に概念的に対応する個人学習環境を構築する。

Azureサービスの習得自体ではなく、イベント駆動、オーケストレーション、入力検証、スキーマ変化、ETL、監視、冪等性を実装してAWS構成への理解を深めることが目的である。

## ドキュメント

- [プロジェクト概要](docs/project-brief.md)：目的、前提、制約、完成条件の正
- [アーキテクチャ](docs/architecture.md)：サービス構成、処理責務、異常系の正
- [学習計画](docs/learning-plan.md)：実装フェーズ、検証項目、利用ツールの正
- [Phase 1の実行手順](docs/learning-plan.md#phase-1-storage)：Terraformの初期化からplan・適用・CSV確認・後片付けまで
- [Phase 1の解説](docs/tutorials/phase-1-storage.md)：CSVの保存先からTerraformのコード、権限、実行結果を理解する
- [Terraform planのPRレビュー](docs/terraform-plan-review.md)：表示処理の確認方法と、CI接続前の未決事項
- [設計判断の記録](docs/adr/README.md)：Subscription分離などの判断と理由
- [開始時の引き継ぎメモ](docs/archive/2026-08-27-chatgpt-handoff.md)：履歴として保管する初期資料

現在の作業状況は、GitHubリポジトリを作成した後にIssueで管理する。
