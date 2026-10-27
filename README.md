# Azure Data Transformation Lab

仕事で予定されているAWSベースのデータ変換層を理解するため、Azure上に概念的に対応する個人学習環境を構築する。

Azureサービスの習得自体ではなく、イベント駆動、オーケストレーション、入力検証、スキーマ変化、ETL、監視、冪等性を実装してAWS構成への理解を深めることが目的である。

## ドキュメント

- [プロジェクト概要](docs/project-brief.md)：目的、前提、制約、完成条件の正
- [アーキテクチャ](docs/architecture.md)：サービス構成、処理責務、異常系の正
- [学習計画](docs/learning-plan.md)：実装フェーズ、検証項目、利用ツールの正
- [AWS版の計画案](docs/aws-learning-plan.md)：Azure Phase 4完了後のAWSコード作成、会社学習環境への持ち込みと構築。Azure Phase 5〜7はAWS 4の完了を待たずに進め、比較学習は構築後
- [Phase 1の実行手順](docs/learning-plan.md#phase-1-storage)：Terraformの初期化からplan・適用・CSV確認まで
- [後片付けと再構築](docs/lab-teardown.md)：学習環境の削除、中止時の復旧、削除後の再構築
- [Phase 1の解説](docs/tutorials/phase-1-storage.md)：CSVの保存先からTerraformのコード、権限、実行結果を理解する
- [Phase 2の解説](docs/tutorials/phase-2-validation.md)：CSV検証、HTTP契約、Managed Identity、依存関係のパッケージ化を理解する
- [Phase 3の解説](docs/tutorials/phase-3-data-factory.md)：Data Factoryの用語、CSVがたどる処理の段階、定義ファイルとの対応を理解する
- [Phase 4の解説](docs/tutorials/phase-4-schema-evolution.md)：列や型が変わったCSVを、どの層で受け入れ、どの層で拒否するかを比較する
- [Terraform planのPRレビュー](docs/terraform-plan-review.md)：OIDCの接続設定とPRコメントでのplan確認
- [stateの共有と移行](docs/terraform-state.md)：専用Storageの構築、既存stateの移行、復旧と保管
- [設計判断の記録](docs/adr/README.md)：Subscription分離などの判断と理由
- [開始時の引き継ぎメモ](docs/archive/2026-08-27-chatgpt-handoff.md)：履歴として保管する初期資料

現在の作業状況はGitHubのIssueで管理する。
