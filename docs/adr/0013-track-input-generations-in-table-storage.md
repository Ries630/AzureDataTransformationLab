# ADR-0013: 入力世代の処理状態をTable Storageの条件付き更新で管理する

- ステータス: 提案
- 日付: 2026-10-18
- 関連: [Issue #20](https://github.com/Ries630/AzureDataTransformationLab/issues/20)、[ADR-0011](0011-coordinate-input-attempts-in-dynamodb.md)

## 背景

Phase 5までの`pl-csv-ingestion`は、処理状態を持たない。同じファイルを再び処理すると、`validated`・`rejected`・`output`の同じパスへ上書きする。そのため次の問題が残っている。

- 重複イベントや手動再実行のたびに、Data Flowのクラスターが起動する。
- 同じパスで1回目がVALID、2回目がINVALIDだと、`output`と`rejected`の両方に結果が残り、どちらが現在の結果か判断できない。
- ETagを確認してから原本をコピーするまでに入力が上書きされると、検証した版とコピーした版が食い違う（[検証する版の特定](../architecture.md#検証する版の特定)）。

Pipelineは`concurrency = 1`で定義しており、同時に起動した実行は順番待ちになる。本番の量や並列処理の要件は決まっていない。

ADFには、SHA-256などのハッシュ関数と、Web Activityの応答ヘッダーを後続へ確実に渡す方法がない。Table StorageのREST APIは、エンティティのETagを応答本文の`odata.etag`でも返す。

## 決定

入力の世代を`landing`の相対パスとETagの組で識別し、世代ごとの処理状態を、入力用StorageのTable`ingestionstate`に1エンティティずつ置く。ADFのWeb Activityから、Managed IdentityでTableのREST APIを呼んで読み書きする。

- 初回は挿入（既存なら409）で取得し、以後の更新は読み取ったときの`odata.etag`を`If-Match`に指定する。条件が合わなければ、上書きせずにPipelineを失敗させる。
- 同時実行は当面`concurrency = 1`で止めるが、状態の正しさはこの直列化に頼らない。
- 出力は世代ごとのパスに置き、`SUCCEEDED`のエンティティが参照する出力を公開済みとする。

AWS版のDynamoDB条件付き書き込み（[ADR-0011](0011-coordinate-input-attempts-in-dynamodb.md)）と同じ形で状態を守り、比べながら学べるためである。新しいサービスを追加せず、将来並列にするときも状態の更新方法を変えずに済む。具体的な状態遷移と出力の配置は[アーキテクチャの冪等性](../architecture.md#冪等性)を正とする。

## 検討した代替

- 状態を持たず、同じパスへの上書きだけで済ませる: 重複のたびにData Flowが動き、VALIDとINVALIDの結果が混在する問題を解消できない。
- Blobの状態ファイルを、直列化を前提に条件なしで上書きする: 最も簡単だが、直列化の前提が崩れても気づけない。BlobのETagは応答ヘッダーでしか返らないため、ADFから`If-Match`の更新を組みにくい。
- Cosmos DB serverless: 条件付き更新とクエリを使えるが、学習環境に新しいサービスと費用を追加する。
- Functionに状態管理のエンドポイントを追加する: Pythonでテストしやすいが、Functionは検証結果を返すだけという責務（[Azure Functionsの責務](../architecture.md#azure-functionsの責務)）を変える。
- 内容のハッシュで識別する: 同じ内容の再投入を同じ入力にできるが、ADFでは計算できず、ADLSの`Content-MD5`はアップロード方法によって設定されない。

## 受け入れた代償

- Tableのキーには`/`、`\`、`#`、`?`を使えないので、相対パスを符号化してキーにする。符号化した長さがキーの上限を超えるパスは処理できない。
- Pipelineの失敗やキャンセルでは状態を`FAILED`に更新できず、`RUNNING`のまま残る。当面は`concurrency = 1`を根拠に、次の実行が引き継ぐ。並列にする場合は、引き継ぐ前にADFの実行状態を確かめる処理が要る。
- 出力のパスが世代ごとに深くなり、Phase 3の`output/<path>`を直接読む確認方法が変わる。
- 同じ内容でもアップロードし直すとETagが変わり、別の世代として再び処理する。

## 再評価の条件

- Pipelineの並列実行が必要になった場合。残った`RUNNING`の引き継ぎ方を見直す。
- 状態を条件で絞り込んで一覧する必要が、Tableのクエリで足りなくなった場合。

## 未検証の点

- `concurrency = 1`で順番待ちになった実行の上限と、上限を超えたときの扱い。
- ADF Studioのデバッグ実行が`concurrency`の対象になるか。
- Web Activityが`If-Match`の不一致（412）や挿入の競合（409）を受けたときに、Activityが失敗として扱われること。
- Web Activityの出力から`odata.etag`を後続のActivityで読めること。
