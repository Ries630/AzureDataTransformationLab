# ADR-0012: スキーマ変化の比較にGlue Sparkを使う

- ステータス: 承認済み
- 日付: 2026-10-12
- 関連: [Issue #32](https://github.com/Ries630/AzureDataTransformationLab/issues/32)

## 背景

入力は共通検証の上限内の少量CSVだが、プロジェクトの目的にはCrawler、Data Catalog、ETLとAzure Mapping Data Flowのスキーマ変化の比較が含まれる。会社構築を先行し、比較の解説は構築後に行う。

## 決定

Glue Spark jobを採用し、Crawlerによる推論と必須列の明示変換・未知列の保持を分けて検証する。版・worker・Timeoutなど運用設定の正は[AWS処理契約](../aws-architecture.md#共通コードと配置)に置く。

## 検討した代替

LambdaだけでCSV変換する案は少量データに適するが、GlueとMapping Data Flowを比較する当初目的を満たせない。Glue Python Shellは小規模変換の候補だが、今回承認されたSparkによる型・スキーマ変化の検証を優先する。

## 受け入れた代償

少量CSVに対してSparkの起動待ちと実行費用が発生する。性能・費用優位性を測定した選択ではない。実機の利用可否と予算は会社で確認する。

## 再評価の条件

会社の予算・SKU制約で利用できない場合、またはGlue比較をプロジェクトの完成条件から外す場合に再評価する。
