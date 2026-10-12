# AWS版の処理契約

対象は[AWS 1 / #32](https://github.com/Ries630/AzureDataTransformationLab/issues/32)で確定した初期構築の契約。CSV規則・変換と比較は[共通アーキテクチャ](architecture.md#比較基準)、実装順序は[AWS計画](aws-learning-plan.md)を正とする。会社のアカウント・権限・予算は未確認で、以下は実装契約であり実機の検証結果ではない。

## 入力と処理経路

```text
S3 landing/ の完成CSV（手動投入）
  → EventBridge → Step Functions Standard
  → 入力世代の取得権を確保 → Lambda検証
      INVALID → rejected/ に原本と検証結果 → 正常終了
      VALID → validated/ に原本と検証結果
            → Crawler完了確認 → Glue ETL .sync
            → staging結果検査 → output/へ配置 → 公開確定

実行Failed / TimedOut / Aborted → CloudWatch Alarm → SNS
EventBridgeが実行開始を配送できない → SQS DLQ → CloudWatch Alarm → SNS
```

初期構築にAthena取得と対応表マスタは含めない。[後から追加する機能](aws-learning-plan.md#後から追加する機能)で入口の前処理とGlue変換へ追加する。

実行用bucketは会社設定で固定する。EventBridgeは当該bucketの`Object Created`、`landing/` prefix、`.csv` suffixに限定する。原本は削除しない。`validated/`、`rejected/`、`staging/`、`output/`、配置用`artifacts/`への書き込みは起動対象外。別bucket、対象外key、必須項目欠落の直接実行はシステムエラーとして拒否する。

## 共通コードと配置

| 項目 | 決定 |
|---|---|
| 検証コードの正 | `functions/validator/validation.py`と既存の純粋検証テスト。Azure入口・import・配置を変更しない |
| Lambdaへの同梱 | ZIP生成時に正の`validation.py`をZIP直下へコピーする。AWS配下に編集用の複製を置かず、生成時にSHA-256一致を検査する |
| Lambda | Python `python3.14`、`arm64`。会社制約がある場合はruntime/architectureを指定して再生成・再検証する |
| Lambda依存 | AWS入口のPEP 723と隣接lockを正とし、Boto3を含めて固定する。対象Linux・Python・CPU向けにZIPを生成する |
| Glue | Glue 5.1（Spark 3.5.6 / Python 3.11）、G.1Xを2 worker、同時job数1。Lambda用の依存・ZIPを流用しない |
| IaC | AWS root・stateはAzureから分離。会社でbackendを指定し、ローカル検証で会社stateへ接続しない |

ランタイムの根拠は[AWS Lambda対応表](https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html)、[Glueリリース情報](https://docs.aws.amazon.com/glue/latest/dg/release-notes.html)。Glue Sparkの採用理由は[ADR-0012](adr/0012-use-glue-spark-for-schema-evolution.md)。会社での利用可能版・SKU・予算は適用前に確認する。

## 世代と参照

EventBridgeの`detail.bucket.name`、`detail.object.key`、`detail.object.etag`を入口にする。EventBridgeのkeyをURLデコードして変更しない。ETagは外側の引用符を正規化して保持し、SDKの条件には引用符付きで渡す。処理キー`inputId`は`[bucket, key, etag]`のUTF-8 JSON配列（余分な空白なし）をSHA-256にした値とする。文字列連結の区切りによる衝突を避ける。

ETagはS3の条件照合用識別子であり、内容のSHA-256やS3 VersionIdとはみなさない。同じkey・ETagで同じ内容を再投入すると同一入力として扱う。メタデータだけの更新を別処理とすることは初期構築の対象外。異なるkeyまたはETagは別入力で、以前の入力への上書き公開は行わない。

Lambdaは固定bucketの対象keyを`GetObject(IfMatch=etag)`で読む。ContentLengthと読み取り上限を用い、検証上限を超える入力は共通検証のサイズRejectとして扱う。SDKの失敗・404・412はINVALIDへ変換せず、システム障害とする。原本コピーは同じ参照に`CopySourceIfMatch=etag`を指定する。コピーの前後で別世代を受理しない。`validated/<inputId>/<attemptId>/source.csv`または`rejected/<inputId>/<attemptId>/source.csv`を、以後の処理が読む固定原本とする。

公開直前にもlandingのHeadObjectでETag一致を確認する。不一致なら`INPUT_CHANGED`として公開を中止する。ただし最終照合と公開はS3上のトランザクションではなく、照合直後の上書きを完全には排除できない。出力は入力keyの最新版という扱いではなく、検証・コピー済みの世代に対する結果として保存する。版の厳密な履歴が必要になった場合はVersionId採用を再評価する。

ワークフローの状態データは次を含み、CSV本文・検証エラー全文は含めない。

| 項目 | 内容 |
|---|---|
| `input` | `bucket`、`key`、`etag`、`inputId` |
| `attempt` | `attemptId`（実行ARNから導出する一意値）、`executionArn` |
| `validation` | `status`、`errorCount`、検証JSONのbucket/key、固定原本のbucket/key |
| `transform` | staging参照、入力行数、出力行数、Glue job run ID |
| `publication` | 公開manifestのbucket/key、完了状態 |

検証JSONは固定原本と同じattempt配下の`validation.json`に保存する。全文は共通`validate_csv`の戻り値のまま保持する。履歴はDynamoDBの世代状態とattemptごとの参照で辿り、サービス固有IDは比較用の値に含めない。

## 実行状態、排他と再実行

DynamoDBのオンデマンドテーブルを処理制御専用に追加する。対応表マスタの保存先ではない。選択理由は[ADR-0011](adr/0011-coordinate-input-attempts-in-dynamodb.md)。世代ごとのitemには`inputId`、元の参照、`status`、所有`executionArn`、`attemptId`、時刻、検証・公開参照を保存する。旧attemptの証跡はS3に残す。

| 現在の状態 | 同一世代への操作 | 結果 |
|---|---|---|
| 未登録 | イベントまたは手動開始 | 条件付きPutで`RUNNING`を取得 |
| `RUNNING` | 重複イベント | 既存実行への参照を返して正常終了。出力・状態を更新しない |
| `SUCCEEDED` / `REJECTED` | 通常イベント・手動開始 | 正常終了のno-op。既存結果を返す |
| `FAILED` | 新しい実行 | 前の実行が終端状態であることを確認し、条件付きUpdateで新attemptを取得 |
| `SUCCEEDED` / `REJECTED` | 手動の`force=true` | 前の実行が終端状態の場合だけ新attemptを取得。自動イベントではforceを受け付けない |
| 古い`RUNNING` | 障害後の手動再実行 | DescribeExecutionでFailed/TimedOut/Abortedを確認してFAILEDへ条件付き遷移後、取得。時刻だけで横取りしない |

すべての更新・公開処理は所有execution/attempt一致を条件とし、旧attemptの遅れた処理が新しい状態を更新しない。重複受付で先行実行が後から失敗した場合は、手動で再実行する。失敗の自動無限再実行はしない。状態itemを保持する間が重複抑止の期間であり、初期構築ではTTLによる自動削除をしない。後片付けで削除する。

Glue Crawlerは一つを共有し、対象を当該attemptのvalidated prefixに更新する。除外パターンで`validation.json`を除き、CSV原本だけを推論対象にする。異なる入力のCrawler・Catalog・変換が干渉しないよう、DynamoDBの別itemで変換区間の排他を取得する。他入力は破棄せずWaitして取得を再試行する。待機上限を設け、期限超過は失敗とする。ロックは成功/失敗時に所有者条件で解放するが、CrawlerがREADY、記録したGlue job runが終端状態になるまで解放しない。中断で残った場合は所有実行の終端、Crawlerの停止完了、旧Glue jobの終了（必要なら停止して終了待機）を確認して手動復旧する。確認できなければロックを維持し、後続実行で共有Catalogを変更しない。

AWS 2の初期設定は全体Timeout 30分、変換排他待機上限15分、Crawler待機上限10分、Glue job timeout10分を基準とする。各待機は全体Timeoutにも従う。会社での起動時間に応じて設定可能にし、増加時は費用を確認する。

一時的なサービス障害・throttlingには回数制限のRetry（最大3回、指数backoff）を設ける。アクセス拒否・INPUT_CHANGED・契約不正・行欠落には自動Retryをしない。Glue実行開始など副作用のある操作は、結果不明時に無条件で重ねず保存済みjob run IDと状態を確認する。Standard実行のRedriveは初期運用の対象外とし、新しい実行による再実行へ統一する。

## 変換と公開

Crawlerの起動API成功だけでは完了としない。完了待機後にLastCrawlの成功・対象実行を確認し、Timeout/失敗でETLへ進めない。Catalogの推論をCSV規則の自動変更に使わない。Glue ETLは固定原本を読み、必須列を明示castし、未知列は文字列として保持するDrift相当の出力を基準とする。Strict/TolerantはAzure比較時の対照であり、AWSの別パイプラインを増やさない。

Glueは`staging/<inputId>/<attemptId>/`にだけ書く。入力論理レコード数、出力行数、必須列castのnull件数を集計し、行数不一致またはcast欠落ならFailとする。金額・日時・未知列は[比較基準](architecture.md#比較基準)に従う。Glue jobは`.sync`で完了を待ち、成功後にLambdaで結果manifestとstagingの実体を検査する。

検査後、データを`output/<inputId>/<attemptId>/`へコピーする。複数partのコピー完了前は公開済みと扱わない。コピー対象全件のkey・サイズ・SHA-256、行数、入力世代、検証結果参照を含む`manifest.json`を最後に保存し、その参照を世代itemへ条件付きUpdateして`SUCCEEDED`を確定する。**公開の正はDynamoDBのSUCCEEDEDとそこに記録したmanifest参照**とし、S3を直接列挙したpartや未確定manifestを消費しない。S3へのコピーが一部成功した後の失敗でも、そのattemptは公開済みにならない。

再実行は新しいattempt配下へ書く。失敗時にはstagingと部分コピーを調査用に残し、成功時にはstagingを削除する。forced再実行中は状態がRUNNINGとなり、その世代の公開結果の参照は確定まで保留する。以前の成功attemptの実体は保持するが、自動で最新版として選ばない。会社で決めた保存期間で実体と証跡を削除する。

INVALIDは原本とJSONの保存完了後に`REJECTED`へ遷移して正常終了する。Reject保存失敗や未知statusはシステム障害になる。Outputは生成しない。

## 障害と通知

CloudWatch Alarmは対象State Machine ARNの`ExecutionsFailed`、`ExecutionsTimedOut`、`ExecutionsAborted`をSumで監視し、欠測は非違反として扱う。SNSは会社で許可されたメール購読先だけを設定する。業務Reject/no-opは成功のため通知対象外。メトリクスは即時配送・実行ごと一通を保証せず、Alarmの状態遷移による通知とする。

EventBridgeからStartExecutionへの配送失敗はState Machineの失敗メトリクスに現れないため、同一リージョンのSQS DLQをターゲットに設定し、メッセージ残留をAlarmで通知する。DLQは自動で再投入せず、原因解消後に会社側で手動再実行する。中断・Timeoutで状態itemがRUNNINGに残るケースも、上記の復旧手順を使う。

Lambda・State Machine・Glueのログには本文や認証情報を出さず、inputId、attemptId、サービス実行IDとエラーcodeを残す。ログ保持・S3保持期限、SNS購読、実通知送信は会社設定とAWS 4の受け入れ確認で確定する。

## 検証の境界

AWS 2ではAWS APIをモックした検証で、条件付き読取/コピー、サイズReject、SDK失敗、二重受付、所有者条件、Retry、公開途中失敗、再実行、ZIP内の共通コードを確認する。固定入力の期待値は[samples/expected](../samples/expected/README.md)を使う。期待値は仕様から派生したもので実Azure採取値とは区別する。

AWS 4ではIAM・EventBridge・Crawler・Glueの実連携、通知・DLQ、同一keyの更新、重複配送、失敗後再実行、行欠落時の非公開を確認する。AWS 1のローカル比較でこれらが実機検証済みになったとは扱わない。
