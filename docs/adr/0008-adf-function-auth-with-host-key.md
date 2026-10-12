# ADR-0008: ADFからFunctionへの呼び出しにFunctionキーを使う

- ステータス: 承認済み
- 日付: 2026-09-24
- 関連: [Issue #17](https://github.com/Ries630/AzureDataTransformationLab/issues/17)、[ADR-0006](0006-scoped-function-refresh-permissions.md)

## 背景

Phase 3ではADF PipelineのAzure Function ActivityがPhase 2の検証Functionを呼び出す。Functionは`http_auth_level=func.AuthLevel.FUNCTION`で、呼び出しにFunctionキーかEasy Authのどちらかが必要になる。

TerraformでLinked Serviceを管理する場合、キーの受け渡し方法を選ぶ必要がある。候補は、Terraformの`azurerm_function_app_host_keys`データソースでキーを取得してLinked Serviceへ設定する方法、Key Vault参照にする方法、Easy Authに切り替えてキーをなくす方法である。

## 決定

Terraformの`azurerm_function_app_host_keys`データソースでdefault function keyを取得し、ADFのFunction Linked Serviceへ設定する。Function側の認証レベルとHTTP契約はPhase 2のまま変更しない。

このデータソースは`Microsoft.Web/sites/host/listkeys/action`を呼ぶため、CI planのrefreshには同Actionの権限が必要になる。既存のFunction App単体のcustom role（ADR-0006）にこのActionを追加し、割り当てscopeは変えない。

キーはTerraformのstateに保存される。stateは非公開の専用Storageで管理済みであり、公開Issue・PRへ貼り付けない運用は既存のplanレビュー手順と同じである。

## 検討した代替

Key Vault参照はキーのローテーションとアクセス分離では優れるが、Key Vaultの作成・シークレット投入・アクセスポリシーという新しいリソースと権限が増える。学習環境の費用と複雑さを抑えるため、このPhaseでは採用しない。

Easy Authへの切り替えはキーをなくせるが、Functionの認証レベル・HTTP契約・Phase 2の検証手順の変更が必要になり、Issue #17の範囲を超える。ADFのManaged IdentityでFunctionを呼ぶ構成は、後続Phaseで認証を見直す場合の候補として残す。

## 受け入れた代償

FunctionキーがstateとLinked Service定義に保存される。キーをローテーションした場合、次のplanでLinked Serviceの差分として反映されるまでADFからの呼び出しは古いキーのままになる。

CIのcustom roleがhost keyの読み取りを含むようになり、CI IdentityがFunctionの秘密を取得できる範囲が広がる。割り当ては対象Function App単体に限定したままである。

## 再評価の条件

- 複数のFunctionや呼び出し元が増え、キー管理の負担が大きくなった場合
- Function側の認証要件が変わり、Easy Authや別の認証方式が必要になった場合
- stateの保管方針が変わり、キーをstateへ置けなくなった場合
