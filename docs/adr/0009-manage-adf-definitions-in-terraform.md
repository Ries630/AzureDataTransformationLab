# ADR-0009: ADFのPipeline・Dataset・Data FlowをTerraformで管理する

- ステータス: 承認済み
- 日付: 2026-09-24
- 関連: [Issue #17](https://github.com/Ries630/AzureDataTransformationLab/issues/17)、[ADR-0002](0002-share-state-in-dedicated-storage.md)

## 背景

Data Factoryには、ADF Studio上で編集してGit連携（adf_publishブランチ）へ発行する方法と、ARM REST API経由でリソースを直接管理する方法がある。Terraformのazurerm providerは後者を使い、Pipeline・Dataset・Data Flow・Triggerをコードとして管理できる。

学習計画は「Azureリソースは原則としてTerraformで管理する」「PortalまたはADF Studioで設定を試した場合も、再現に必要な設定は最終的にTerraformまたはGit管理された定義へ戻す」と定めており、Phase 7でIaCへの回収を確認する。

## 決定

Pipeline・Dataset・Data Flow・Trigger・Linked ServiceをTerraformの`azurerm_data_factory_*`リソースとして管理し、ADF Studioは閲覧・確認用に使う。ADFのGit連携は有効にしない。

Pipelineのactivitiesは`infra/terraform/adf/csv_ingestion.activities.json`、Data Flowのスクリプトは`infra/terraform/adf/transform_orders.dfsql`に置き、`templatefile`・`file`でTerraformへ読み込む。定義の履歴とレビューはGitへ残る。

## 検討した代替

ADFのGit連携はStudio上の編集と発行をGitへ記録できるが、Terraform管理のインフラと別の変更経路が生まれ、同じリソースを2経路で変更し得る状態になる。Phase 7のIaC回収でも差分の吸収が必要になるため採用しない。

ARM template deployment経由での管理も可能だが、azurerm 5.3.0に専用リソースが揃っているため、型付きの差分と依存関係を得られる専用リソースを使う。

## 受け入れた代償

ADF StudioでGUI編集した内容は即座にはTerraformへ反映されず、手で定義へ戻す必要がある。Pipeline JSONとData FlowスクリプトはTerraformの`validate`では意味的な正当性まで確認できず、実際の適用と実行で初めて検証される。

`azurerm_data_factory_pipeline`の`activities_json`内の参照は名前だけのため、Terraformの依存グラフに現れない。作成順序は`depends_on`で明示する必要がある。

## 再評価の条件

- Data FlowやPipelineの数が増え、JSON管理の差分確認が困難になった場合
- Studioでの対話的な開発が主な作業形態になった場合
