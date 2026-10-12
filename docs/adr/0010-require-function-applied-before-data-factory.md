# ADR-0010: Data Factory有効化の前にFunction Appを適用済みにする

- ステータス: 承認済み
- 日付: 2026-10-12
- 関連: [Issue #40](https://github.com/Ries630/AzureDataTransformationLab/issues/40)

## 背景

`data.azurerm_function_app_host_keys.validator`に`depends_on = [azurerm_function_app_flex_consumption.function]`を置き、初回構築でFunction Appの作成完了後にキーを読む設計にしていた。一方でFunction Appの`app_settings`には、AzureRM 5.3.0のRead側が`AzureWebJobsStorage`をstateへ入れない既知差分（[ADR-0007](0007-set-flex-max-instance-count.md)の検証結果参照）があり、planのたびにFunction Appへ「更新あり」のpending changeが出る。`depends_on`で結ばれたdata sourceは参照先にpending changeがあるとapplyまで読み取りを遅延するため、`default_function_key`がunknownになり、`azurerm_data_factory_linked_service_azure_function.validator`の`key`が毎回「更新あり」のplan差分になった。

## 決定

data sourceから`depends_on`を削除し、plan時点でFunctionキーを読む。代わりに、Function Appを作成・適用してから`data_factory_enabled`を有効にする順序を運用手順とする。

## 検討した代替

- `depends_on`を維持する案は、既知差分がある限りLinked Serviceのkey差分が消えないため採用しない。
- Linked Serviceの`key`を`ignore_changes`する案は、キーをローテーションしたときの更新をTerraformが検出できなくなるため採用しない。
- Function App側の既知差分を`ignore_changes`で止める案は、将来のUpdateで不正な接続文字列をPUTする恐れがあるため採用しない。

## 受け入れた代償

Function App未作成のまま`data_factory_enabled = true`でplanすると、data sourceの読み取りがエラーになりplanが失敗する。初回構築や環境の再構築では、Function Appを先にplan・applyしてからData Factoryを有効にする2段階の手順が必要になる。既存の[学習計画](../learning-plan.md)はPhase 2でFunction Appを先に適用する順序なので、手順の変更はない。

## 再評価の条件

- AzureRMが`app_settings`の既知差分を解消し、Function Appにpending changeが出なくなった場合、`depends_on`の復帰を検討する。
