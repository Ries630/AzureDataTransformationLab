# ADR-0002: 学習用stateを専用Storageで共有する

- ステータス: 承認済み
- 日付: 2026-09-03
- 関連: [Issue #12](https://github.com/Ries630/AzureDataTransformationLab/issues/12)、[Issue #9](https://github.com/Ries630/AzureDataTransformationLab/issues/9)

## 背景

既存の学習用7リソースはlocal stateで管理されている。CIで空のstateを使うと既存リソースも作成対象として表示され、実際の変更をレビューできない。stateには機密属性もあるため、公開artifactやGitで受け渡せない。

Issue #9ではremote backendを対象外としていたが、CI接続に必要な前提として別のsub-issueに切り出して進めることが承認された。

## 決定

学習用stateはPersonal-Sandbox内の専用Azure Blob Storageで共有する。学習データと保存先の削除ライフサイクルを分け、学習環境の破棄時も対応関係と復旧元を保持する。Blobのバージョニングを使うため、保存先は非HNSのStorageとする。

AzureRM backendのEntra認証とBlob leaseを利用する。初期構築用rootは分離し、そのbootstrap stateは手元で機密バックアップを保管する。操作方法と保護設定の正は[remote stateの手順](../terraform-state.md)とTerraform定義に置く。

## 検討した代替

- local stateをCIへ都度コピーする方式は、同期忘れや古いコピーからのplanが起きるため採用しない。
- 学習データと同じStorageにstateを置く方式は、学習環境の後片付けとstateの存続が結び付くため採用しない。
- HCP Terraformは追加のサービスと運用を持ち込むため、今回の対象に含めない。

## 受け入れた代償

専用Storageの従量料金と権限管理が増える。bootstrap stateの機密バックアップは手元で管理する必要がある。CIのplanでもlease操作のためstate containerへの権限が必要であり、学習リソースに対する読み取り権限とは分けて管理する。

## 根拠

- [AzureRM backend](https://developer.hashicorp.com/terraform/language/backend/azurerm): Entra認証、Blobによるlocking、container単位のデータ権限
- [Blob versioning](https://learn.microsoft.com/azure/storage/blobs/versioning-overview): HNSの有効なアカウントではバージョニングを利用できない
