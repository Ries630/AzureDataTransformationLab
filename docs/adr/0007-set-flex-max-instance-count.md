# ADR-0007: HTTP Functionの最大インスタンス数を40に設定する

- ステータス: 提案（Azure適用・max40比較検証待ち）
- 現Azure設定: 最大インスタンス数1
- Azure適用: 未承認
- 日付: 2026-09-08
- 関連: [Issue #16](https://github.com/Ries630/AzureDataTransformationLab/issues/16)

## 背景

Flex Consumptionの最大インスタンス数はスケール上限であり、既定値は100、設定範囲は1〜1,000である。MicrosoftはHTTP Functionで40未満の上限を使うと、負荷が上限を超えたときに要求失敗やスロットリングの長期化が起き得ると説明している。[公式の移行ガイド](https://learn.microsoft.com/en-us/azure/azure-functions/migration/migrate-plan-consumption-to-flex#configure-scale-and-concurrency-settings)を参照した。

現Azureの上限は1である。連続curlでは、約212 msのHTTP 200、約60,092 msのHTTP 503、約200 msのHTTP 200が観測された。Node実装でも同様の並びがあり、単発要求と通常ハンドラーの別経路では`VALID`を確認できた。認証待機上限を修正した後も連続要求の失敗は残る。一方、通常版の再発行後に最大数1で実施した2要求の同時実行は、どちらもHTTP 200となった。その後の4ケース逐次検証では正常CSVが200、不正CSVが503となり、未解消である。上限1は公式の注意に該当する原因候補だが、現在の観測だけでは容量枯渇を示せていない。上限40で同じ逐次・小規模同時実行を比較し、改善を確認する必要がある。

## 決定

Functionの最大インスタンス数を40へ変更する提案とする。40は常時起動数ではなく、負荷時のスケール上限である。インスタンスメモリ2048 MB、HTTP同時実行数1、Always Ready 0は維持する。正となる設定値は[アーキテクチャ](../architecture.md#azure-functionsの責務)に置く。

40は、HTTP Functionで40未満を避ける公式の注意を満たしつつ、既定値100をそのまま採用せず、学習用環境の同時稼働量を抑える値として選んだ。最大インスタンス数は月額費用を保証する上限ではない。Azureへの適用は、max40を含むTerraform planを提示し、明示承認を得てから行う。

## 検討した代替

- 最大インスタンス数1を維持する案は、公式の注意の対象となり、観測した断続的な503を説明する候補を残すため採用しない。
- 既定値100を使う案は、負荷時の同時稼働量が学習環境に対して大きくなるため採用しない。
- 40未満の値を選ぶ案は、HTTP Functionでの要求失敗とスロットリング長期化に関する公式の注意を受けるため採用しない。

## 受け入れた代償

負荷が発生したときに最大40台までスケールし得るため、上限1より実行費用が増える可能性がある。Always Readyは0のままなので、40台を常時稼働させる設定ではない。上限40へ変更しても認証、Storage、RBAC、実行環境の問題を解消する保証はなく、比較検証が必要である。

## 再評価の条件

- max40適用後の同じHTTP要求比較で、503発生率または待ち時間が改善しない場合
- 実行費用、サブスクリプションのクォータ、または学習用の費用上限に影響が出た場合
- Flex Consumptionのスケール上限に関する公式要件が変わった場合

## 根拠

- [Microsoft Learn: Migrate Consumption plan apps to Flex Consumption in Azure Functions](https://learn.microsoft.com/en-us/azure/azure-functions/migration/migrate-plan-consumption-to-flex#configure-scale-and-concurrency-settings)
