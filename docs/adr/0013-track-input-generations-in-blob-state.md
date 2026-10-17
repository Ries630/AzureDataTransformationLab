# ADR-0013: 入力世代の処理状態をBlobの状態ファイルで管理する

- ステータス: 提案
- 日付: 2026-10-17
- 関連: [Issue #20](https://github.com/Ries630/AzureDataTransformationLab/issues/20)、[ADR-0011](0011-coordinate-input-attempts-in-dynamodb.md)

## 背景

Phase 5までの`pl-csv-ingestion`は、処理状態を持たない。同じファイルを再び処理すると、`validated`・`rejected`・`output`の同じパスへ上書きする。そのため次の問題が残っている。

- 重複イベントや手動再実行のたびに、Data Flowのクラスターが起動する。
- 同じパスで1回目がVALID、2回目がINVALIDだと、`output`と`rejected`の両方に結果が残り、どちらが現在の結果か判断できない。
- ETagを確認してから原本をコピーするまでに入力が上書きされると、検証した版とコピーした版が食い違う（[検証する版の特定](../architecture.md#検証する版の特定)）。

一方で、Pipelineは`concurrency = 1`で定義しており、同時に起動した実行は順番待ちになる。共有のData Flowを同時に使うことはなく、AWS版の変換ロックに当たる排他はすでにある。

ADFには、SHA-256などのハッシュ関数と、Web Activityの応答ヘッダーを後続へ確実に渡す方法がない。存在の確認にはGet Metadataの`exists`を使える。

## 決定

入力の世代を`landing`の相対パスとETagの組で識別し、世代ごとの処理状態を、入力用Storageの新しいfilesystem`state`に置くJSONファイルで管理する。ファイルはADFのWeb Activityから、Managed IdentityでBlobのREST APIを呼んで読み書きする。

- 同時実行の排他は、Pipelineの`concurrency = 1`に任せる。状態ファイルの初回作成だけを`If-None-Match: *`の条件付き書き込みにし、排他の前提が崩れたときに上書きせず失敗させる。
- 出力は世代ごとのパスに置き、状態ファイルの`SUCCEEDED`が参照する出力を公開済みとする。

新しいサービスを増やさず、AWS版のDynamoDB条件付き書き込みと同じ「条件付きで状態を作る」考え方を、学習環境で既に使っているStorageのAPIで確かめられるためである。具体的な状態遷移と出力の配置は[アーキテクチャの冪等性](../architecture.md#冪等性)を正とする。

## 検討した代替

- 状態を持たず、同じパスへの上書きだけで済ませる: 重複のたびにData Flowが動き、VALIDとINVALIDの結果が混在する問題を解消できない。
- Azure Table Storage: 状態を一覧しやすいが、RowKeyに`/`を使えないため、パスの符号化が必要になる。ADFからの読み書きもWeb Activityになり、Blobと手間が変わらない。
- Cosmos DB serverless: 条件付き書き込みとクエリを使えるが、学習環境に新しいサービスと費用を追加する。
- Functionに状態管理のエンドポイントを追加する: Pythonでテストしやすいが、Functionは検証結果を返すだけという責務（[Azure Functionsの責務](../architecture.md#azure-functionsの責務)）を変える。
- 内容のハッシュで識別する: 同じ内容の再投入を同じ入力にできるが、ADFでは計算できず、ADLSの`Content-MD5`はアップロード方法によって設定されない。比較のために状態ファイルへ記録するだけにする。

## 受け入れた代償

- 状態の更新は条件付きにしないので、`concurrency = 1`を外すと、同じ世代の状態を複数の実行が上書きし得る。AWS版は全更新を所有者で条件付けるが、Azure版はPipelineの直列化を前提にする。
- Pipelineの失敗やキャンセルでは状態を`FAILED`に更新できず、`RUNNING`のまま残る。次の実行は、排他の前提から前の所有者が終了していると判断して引き継ぐ。
- 出力のパスが世代ごとに深くなり、Phase 3の`output/<path>`を直接読む確認方法が変わる。
- 同じ内容でもアップロードし直すとETagが変わり、別の世代として再び処理する。

## 再評価の条件

- Pipelineの並列実行が必要になった場合。
- ADF Studioのデバッグ実行や手動実行が`concurrency`の対象外で、同じ世代を同時に処理できると確かめた場合。

## 未検証の点

- `concurrency = 1`で順番待ちになった実行の上限と、上限を超えたときの扱い。
- ADF Studioのデバッグ実行が`concurrency`の対象になるか。
- Web Activityが`If-None-Match`ヘッダー付きのPUTで412を受けたときに、Activityが失敗として扱われること。
