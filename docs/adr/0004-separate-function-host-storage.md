# ADR-0004: Azure FunctionsのホストStorageと入力Storageを分離する

- ステータス: 承認済み
- Azure検証: Storage再構築（7件）、サンプル配置、承認済みFunction基盤（8件）の適用とコード発行を完了。AzureのIdentity接続設定は構成と一致。キー付きHTTPは503またはタイムアウトとなり、Managed Identityによる入力読取の実証は未完了
- 日付: 2026-09-07
- 関連: [Issue #16](https://github.com/Ries630/AzureDataTransformationLab/issues/16)

## 背景

Phase 2のFunctionは、学習用ADLS Gen2の`landing`からCSVを読み取る。Azure Functionsは、実行状態を保持するホストStorageと、Flex Consumptionのデプロイパッケージを置くStorageも必要とする。入力データとFunctionの運用データは、権限、ライフサイクル、復旧手順が異なる。

ホストStorageを入力Storageと共有すると、Functionの実行に必要な権限が原本の保存先へ及び、入力データの保護境界と再構築手順が複雑になる。学習用StorageはIssue #22の後片付けで削除済みであり、入力Storageの再構築はFunction基盤とは別のplan・適用手順で扱う。

また、Function Appの作成時点で、割り当てるUser Assigned Managed Identityとホスト・デプロイStorageのRBACが利用できなければ、ホスト接続やデプロイパッケージの初期化に失敗し得る。先にIdentityとロールを作成し、反映を確認してからFunction Appを作る順序が必要である。

## 決定

- 入力Storageと、Function専用のホスト・デプロイStorageを分離する。
- FunctionにはUser Assigned Managed Identityを割り当てる。Identityには入力Storageの`landing`に対する`Storage Blob Data Reader`だけを与え、入力CSVのコピーや書き込みを行わせない。
- 同じIdentityには、専用のホスト・デプロイStorageに対する`Storage Blob Data Owner`を与える。Ownerにはデプロイに必要なContributor相当の権限が含まれるため、同じIdentityへ別のContributor割り当ては行わない。
- Infrastructureを適用する操作者には、デプロイ用コンテナーを初期作成するための専用Storage上の権限だけを与える。操作者の権限とFunctionのIdentityの権限を混同しない。
- IdentityとRBAC割り当てを先に作成し、専用Storageのデプロイ領域が利用可能になってからFunction Appを作成する。接続はShared KeyではなくIdentityベースとする。

HTTP契約、入力検証規則、実行時設定は[アーキテクチャ](../architecture.md#azure-functionsの責務)を正とする。リソースの作成順序、再構築、plan・適用は[学習計画のPhase 2](../learning-plan.md#phase-2-azure-functionsによる入力検証)を参照する。

## 検討した代替

入力Storageを`AzureWebJobsStorage`とデプロイ先にも使う案は、ホスト運用の権限と原本データの権限を同じ境界に集めるため採用しない。Storage接続文字列やアカウントキーを使う案も、資格情報の配布と失効を別に管理する必要があるため採用しない。

通常のLinux Consumptionを使う案は、Linux Consumptionの退役予定と新しいPythonランタイムの提供制約を受けるため採用しない。PremiumまたはDedicatedを使う案は、少量の検証に対して常時稼働の費用と運用を増やすため採用しない。

## 受け入れた代償

Storage、User Assigned Managed Identity、複数のRBAC割り当てを管理する必要がある。RBACの反映を待ってからFunction Appを作成する工程も増える。入力Storageを再構築する場合は、Function基盤のplanと別に確認・承認する。

## 再評価の条件

- Functionが入力Storageへ書き込む必要が生じた場合
- 入力Storageとホスト・デプロイStorageを分離できない制約が生じた場合
- Flex Consumption、対象ランタイム、または対象リージョンの提供状況が変わった場合
- Azure上のplanまたは実機検証で、Identityベースのホスト接続・デプロイ・`landing`読み取りの組み合わせが成立しない場合

## 根拠

- [Azure Functions Flex Consumption plan](https://learn.microsoft.com/en-us/azure/azure-functions/flex-consumption-plan)
- [Create and manage Function Apps in a Flex Consumption plan](https://learn.microsoft.com/en-us/azure/azure-functions/flex-consumption-how-to)
- [Configure connections to remote services in Azure Functions](https://learn.microsoft.com/en-us/azure/azure-functions/manage-connections?tabs=identity)
- [How to target Azure Functions runtime versions](https://learn.microsoft.com/en-us/azure/azure-functions/set-runtime-version)
- [Migrate from the legacy Consumption plan to Flex Consumption](https://learn.microsoft.com/en-us/azure/azure-functions/migration/migrate-plan-consumption-to-flex)
- [Azure built-in roles for Storage](https://learn.microsoft.com/en-us/azure/role-based-access-control/built-in-roles/storage)
