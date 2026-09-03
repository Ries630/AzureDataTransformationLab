# ADR-0001: 学習用リソースを専用Subscriptionへ分離する

- ステータス: 承認済み
- 日付: 2026-09-03
- 関連: [Issue #7](https://github.com/Ries630/AzureDataTransformationLab/issues/7)

## 背景

Azure CLIの既定Subscriptionである`Personal-Data`には重要な既存リソースがある。
本プロジェクトではTerraformによる作成と後片付けを学ぶため、対象の取り違えが既存データへ影響しない境界が必要である。
学習用の`Personal-Sandbox`はすでに用意されている。

## 決定

学習用リソースは`Personal-Sandbox`へ分離する。
既存データと学習用リソースのライフサイクルをSubscription単位で分け、CLIの既定値に依存しない実行にする。

対象指定と実行手順は[学習計画のPhase 1](../learning-plan.md#phase-1-storage)を参照する。

## 検討した代替

`Personal-Data`内でResource Groupだけを分ける案を検討した。
Resource Group単位の後片付けは可能だが、既定Subscriptionを利用する操作と重要な既存リソースが同じSubscriptionに残るため、専用Subscriptionを使う案を選んだ。

## 受け入れた代償

SubscriptionごとにResource Providerの登録と実行権限を確認する必要がある。
実行時には対象Subscriptionを明示し、planでも対象を照合する手間を引き受ける。
