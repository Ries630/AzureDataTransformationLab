# AWS版の処理契約

この文書は、AWS版のパイプラインが入力をどう識別し、どの条件で検証・変換・公開するか、障害と再実行をどう扱うかを定める。内容は[AWS 1 / #32](https://github.com/Ries630/AzureDataTransformationLab/issues/32)で確定した初期構築の契約である。CSVの規則と変換・比較の基準は[共通アーキテクチャ](architecture.md#比較基準)、実装の順序は[AWS計画](aws-learning-plan.md)、操作のコマンドは[配置と運用](aws-implementation.md)を正とする。

ここに書いた内容は実装の契約であり、実機で確かめた結果ではない。会社のアカウント、権限、予算は未確認で、実機での確認はAWS 4で行う。

## 用語

AWS版では、同じCSVが重ねて届いた場合や処理が途中で失敗した場合でも、どの入力に対するどの実行の結果なのかを辿れるようにする。そのために、次の用語で入力と実行を区別する。

| 用語 | 意味 |
|---|---|
| 入力の世代 | bucket・key・ETagの組で識別する入力。同じkeyに別の内容を置き直すと、別の世代になる。処理キーは`inputId` |
| attempt | 同じ世代を処理するStep Functionsの実行1回ずつ。`attemptId`で区別し、出力はattemptごとのprefixに書く |
| 世代item | 世代ごとの処理状態を持つDynamoDBのitem。`status`は`RUNNING`、`SUCCEEDED`、`REJECTED`、`FAILED`のいずれか |
| 変換ロック | 共有のCrawler・Data Catalog・Glue jobを一度に1つの入力だけが使うための、DynamoDBの別item（`__transform_lock__`） |
| pending | CrawlerやGlue jobの開始APIを呼ぶ直前に、変換ロックへ記録する「開始したかもしれない」という印 |
| 固定原本 | 検証のときにlandingからコピーした原本。以後の処理はlandingではなく、これを読む |
| 公開 | 世代itemを`SUCCEEDED`にし、manifestへの参照を記録すること。S3に出力を置いただけでは公開にならない |

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
EventBridgeが実行開始を配信できない → SQS DLQ → CloudWatch Alarm → SNS
```

初期構築には、Athenaによる取得と対応表マスタを含めない。これらは[後から追加する機能](aws-learning-plan.md#後から追加する機能)として、入口の前処理とGlueの変換へ追加する。

### 起動の対象

- 実行用のbucketは、会社の設定で固定する。
- `data_prefix`は、このbucket内の自分用のnamespaceである。既存の共有bucketでは必須で、新規の専用bucketでは既定値が空文字になる。以下の`landing/`などの論理prefixは、すべて`data_prefix`の下に置く。
- EventBridgeは、当該bucketの`Object Created`のうち、`landing/` prefixかつ`.csv` suffixのものだけを対象にする。`validated/`、`rejected/`、`staging/`、`output/`、配置用の`artifacts/`への書き込みでは起動しない。
- 直接実行で、別のbucket、対象外のkey、必須項目が欠けた入力を指定した場合は、システムエラーとして拒否する。
- 原本は削除しない。

## 共通コードと配置

| 項目 | 決定 |
|---|---|
| 検証コードの正 | `functions/validator/validation.py`と既存の純粋検証テスト。Azure入口・import・配置を変更しない |
| Lambdaへの同梱 | ZIP生成時に正の`validation.py`をZIP直下へコピーする。AWS配下に編集用の複製を置かず、生成時にSHA-256一致を検査する |
| Lambda | Python `python3.14`、`arm64`。会社制約がある場合はruntime/architectureを指定して再生成・再検証する |
| Lambda依存 | AWS入口のPEP 723と隣接lockを正とし、Boto3を含めて固定する。対象Linux・Python・CPU向けにZIPを生成する |
| Glue | Glue 5.1（Spark 3.5.6 / Python 3.11）、G.1Xを2 worker、同時job数1。Lambda用の依存・ZIPを流用しない |
| IaC | AWS root・stateはAzureから分離。会社でbackendを指定し、ローカル検証で会社stateへ接続しない |

ランタイムの根拠は[AWS Lambdaの対応表](https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html)と[Glueのリリース情報](https://docs.aws.amazon.com/glue/latest/dg/release-notes.html)、Glue Sparkを採用した理由は[ADR-0012](adr/0012-use-glue-spark-for-schema-evolution.md)にある。会社で利用できる版、SKU、予算は、適用の前に確認する。

## 世代と参照

### 入力の識別

EventBridgeのイベントから`detail.bucket.name`、`detail.object.key`、`detail.object.etag`を取り出して入口にする。keyはURLデコードせず、受け取ったまま使う。ETagは外側の引用符を除いて保持し、SDKの条件に渡すときは引用符を付ける。

処理キー`inputId`は、`[bucket, key, etag]`をUTF-8のJSON配列（余分な空白なし）にし、そのSHA-256をとった値である。文字列を区切り文字で連結しないのは、区切り文字を含むkeyが別の入力と同じ値になるのを避けるためである。

ETagは、S3が条件付きの読み取りやコピーで照合するための識別子であり、内容のSHA-256でもS3のVersionIdでもない。同じkey・ETagで同じ内容を再投入すると、同じ入力として扱う。メタデータだけを更新した場合に別の処理とすることは、初期構築の対象外である。keyかETagが異なれば別の入力であり、以前の入力の結果を上書きして公開することはない。

### 原本の読み取りと固定

Lambdaは、固定bucketの対象keyを`GetObject(IfMatch=etag)`で読む。ContentLengthと読み取りの上限を使い、検証の上限を超える入力は、共通検証のサイズRejectとして扱う。SDKの失敗・404・412はINVALIDに変換せず、システム障害とする。

原本のコピーにも、同じ参照で`CopySourceIfMatch=etag`を指定する。こうすると、読み取りとコピーのあいだにkeyが置き換わっても、別の世代を受理しない。コピー先の`validated/<inputId>/<attemptId>/source.csv`または`rejected/<inputId>/<attemptId>/source.csv`が固定原本になる。

### 公開直前の照合とその限界

公開の直前にも、landingのHeadObjectでETagが一致することを確かめる。一致しなければ`INPUT_CHANGED`として公開を中止する。

ただし、この照合と公開はS3上のトランザクションではないため、照合の直後に行われた上書きまでは排除できない。そこで出力は、入力keyの最新版としてではなく、検証・コピー済みの世代に対する結果として保存する。版の厳密な履歴が必要になった場合は、VersionIdの採用を再評価する。

### ワークフローの状態データ

Step Functionsの状態データには次を含める。CSVの本文と検証エラーの全文は含めない。

| 項目 | 内容 |
|---|---|
| `input` | `bucket`、`key`、`etag`、`inputId` |
| `attempt` | `attemptId`（実行ARNから導出する一意値）、`executionArn` |
| `validation` | `status`、`errorCount`、検証JSONのbucket/key、固定原本のkey、入力行数（VALIDの場合） |
| `transform` | staging参照、Glue job run ID（`.sync`の成功後に記録） |
| `publication` | 公開manifestのbucket/key、完了状態 |

出力行数は状態データに持たず、Glueがstagingに書くmanifestで入力行数と照合する。検証結果の全文は、共通`validate_csv`の戻り値のまま、固定原本と同じattempt配下の`validation.json`に保存する。履歴は、DynamoDBの世代状態とattemptごとの参照で辿る。サービス固有のIDは比較用の値に含めない。

## 実行状態、排他と再実行

処理の制御には、専用のDynamoDBオンデマンドテーブルを追加する。対応表マスタの保存先ではない。選択の理由は[ADR-0011](adr/0011-coordinate-input-attempts-in-dynamodb.md)にある。テーブルには、世代itemと変換ロックのitemを置く。

### 世代itemと状態遷移

世代itemには、`inputId`、元の参照、`status`、所有する`executionArn`と`attemptId`、時刻、検証・公開の参照を保存する。古いattemptの証跡はS3に残す。

同じ世代に対する操作の結果は、現在の状態によって次のように決まる。

| 現在の状態 | 同一世代への操作 | 結果 |
|---|---|---|
| 未登録 | イベントまたは手動開始 | 条件付きPutで`RUNNING`を取得 |
| `RUNNING` | 重複イベント | 既存実行への参照を返して正常終了。出力・状態を更新しない |
| `SUCCEEDED` / `REJECTED` | 通常イベント・手動開始 | 正常終了のno-op。既存結果を返す |
| `FAILED` | 新しい実行 | 前の実行が終端状態であることを確認し、旧所有者を条件にしたPutで新attemptを取得 |
| `SUCCEEDED` / `REJECTED` | 手動の`force=true` | 前の実行が終端状態の場合だけ新attemptを取得。自動イベントではforceを受け付けない |
| 古い`RUNNING` | 障害後の手動再実行 | DescribeExecutionでFailed/TimedOut/Abortedを確認し、旧所有者を条件にしたPutで新attemptを取得。時刻だけで横取りしない |

すべての更新と公開は、所有するexecutionとattemptの一致を条件にする。遅れて動いた古いattemptの処理が、新しい状態を更新しないようにするためである。

- 重複して受け付けた後で先行の実行が失敗した場合は、手動で再実行する。失敗を自動で無限に再実行することはしない。
- 世代itemを保持している間が、重複を抑止する期間になる。初期構築ではTTLによる自動削除をせず、後片付けで削除する。

### 変換区間の排他

Glue Crawlerは1つを共有し、実行のたびに対象を当該attemptのvalidated prefixへ更新する。除外パターンで`validation.json`を除き、CSVの原本だけを推論の対象にする。共有しているので、別の入力のCrawler・Catalog・変換が同時に動くと互いに干渉する。そこで、変換区間に入る前に、変換ロックで排他を取得する。

- ロックを取得できない入力は、破棄せずにWaitして取得を再試行する。待機には上限を設け、超えたら失敗とする。
- ロックは成功時も失敗時も、所有者を条件にして解放する。ただし、CrawlerがREADYになり、当該attemptのGlue job runが終端状態になるまでは解放しない。job run IDが未記録の場合は、引数`--attempt_id`が一致するjob runをすべて確認する。一致するjob runが1件もない場合も、開始されなかったとは判断せずにロックを維持し、[管理者の復旧](#中断で残ったロックの復旧)でpendingを解除する。

CrawlerとGlue jobの開始APIを呼ぶ前には、変換ロックにpendingを記録する。開始APIの応答が失われると、サービスが開始されたかどうかを処理の側から判断できないためである。pendingが残っている間は、対象のcrawlやjob runの終了を確認できない限り、ロックを解放しない。

### 中断で残ったロックの復旧

TimeoutやAbortで実行が止まると、変換ロックが残ることがある。この場合は、次をすべて確認してから手動で復旧する。

- 所有する実行が終端状態である。
- Crawlerの停止が完了している。
- 旧Glue jobが終了している（必要なら停止し、終了を待つ）。

確認できなければロックを維持し、後続の実行で共有のCatalogを変更しない。

開始APIが確実に拒否された場合でも、pendingが残ることがある。このときは、管理者がCloudTrailで要求・対象・時刻・拒否の証跡とサービスの終端を照合し、所有者を条件にして該当するpendingだけを解除してから復旧する。手順は[操作手順](aws-implementation.md#開始が確実に拒否された場合の管理者復旧)にある。証跡が足りない場合や、開始の結果が不明な場合は解除しない。

### 待機とTimeoutの上限

AWS 2の初期設定は次を基準とする。各待機は、実行全体のTimeoutにも従う。

| 対象 | 初期値 |
|---|---|
| 実行全体のTimeout | 30分 |
| 変換ロックの待機上限 | 15分 |
| Crawlerの待機上限 | 10分 |
| Glue jobのtimeout | 10分 |

会社での起動時間に応じて設定できるようにし、値を増やすときは費用を確認する。

### Retry

- 一時的なサービス障害とthrottlingには、回数を制限したRetry（最大3回、指数backoff）を設ける。
- アクセス拒否、`INPUT_CHANGED`、契約の不正、行の欠落は、自動でRetryしない。
- Glue実行の開始など副作用のある操作は、結果が不明なときに無条件で重ねて呼ばない。保存したjob run ID、未記録なら引数`--attempt_id`で特定したjob runの状態を確認する。
- StandardのRedriveは初期運用の対象外とし、再実行は新しい実行に統一する。

## 変換と公開

### Crawlerの完了確認

Crawlerは、起動APIが成功しただけでは完了としない。完了を待ってから、LastCrawlが成功し、今回の起動による実行であることを確かめる。Timeoutや失敗の場合は、ETLへ進めない。Catalogの推論結果を、CSV規則の自動変更には使わない。

### Glue ETLの出力と検査

Glue ETLは固定原本を読み、必須列を明示的にcastし、未知列は文字列として保持する。この出力を、Azureで比べたDrift相当の基準とする。Strict/TolerantはAzureで比較したときの対照であり、AWSで別のパイプラインを増やすことはしない。

Glueは`staging/<inputId>/<attemptId>/`にだけ書き込む。入力の論理レコード数、出力行数、必須列のcastで生じたnullの件数を集計し、行数が一致しないか、castで値が欠けた場合はFailとする。金額・日時・未知列の扱いは[比較基準](architecture.md#比較基準)に従う。Step FunctionsはGlue jobの完了を`.sync`で待ち、成功後にLambdaが完了結果の`Id`をjob run IDとして変換ロックと状態データへ記録してから、結果のmanifestとstagingの実体を検査する。`.sync`は完了まで結果を返さないため、Glueの実行中や、Glueの失敗で止まった実行では、job run IDは記録されない。Glueが成功しても、記録するLambdaが失敗した場合や、記録の前に実行が止まった場合は、同じく未記録になる。

### 公開の確定

検査を通ったデータは、`output/<inputId>/<attemptId>/`へコピーする。複数partのコピーがすべて終わるまでは、公開済みとして扱わない。最後に`manifest.json`を保存する。manifestには、コピーした全件のkey・サイズ・SHA-256、行数、入力の世代、検証結果への参照を含める。そのmanifestへの参照を世代itemへ条件付きUpdateで記録し、`SUCCEEDED`を確定する。

**公開の正は、DynamoDBのSUCCEEDEDと、そこに記録したmanifestの参照である。** S3を直接列挙して見つけたpartや、確定していないmanifestは消費しない。S3へのコピーが一部成功した後に失敗した場合も、そのattemptは公開済みにならない。

### 再実行したときの出力

再実行は、新しいattempt配下へ書き込む。

- 失敗したattemptのstagingと部分的なコピーは、調査用に残す。成功したattemptのstagingは削除する。
- forced再実行の間は世代itemが`RUNNING`になり、その世代の公開結果への参照は、確定するまで保留になる。
- 以前に成功したattemptの実体は保持するが、自動で最新版として選ぶことはない。
- 実体と証跡は、会社で決めた保存期間で削除する。

### 業務Reject

INVALIDの場合は、原本とJSONの保存が終わってから`REJECTED`へ遷移し、正常終了する。Outputは生成しない。Rejectの保存に失敗した場合や、未知のstatusが返った場合はシステム障害になる。

## 障害と通知

障害の検知は、Step Functionsの実行が失敗する場合と、EventBridgeが実行を開始できない場合とで、仕組みが異なる。

| 障害 | 検知の仕組み |
|---|---|
| 実行のFailed・TimedOut・Aborted | 対象State Machine ARNの`ExecutionsFailed`、`ExecutionsTimedOut`、`ExecutionsAborted`を、CloudWatch AlarmがSumで監視する。欠測は非違反として扱う |
| EventBridgeからStartExecutionへの配信失敗 | State Machineの失敗メトリクスには現れない。同一リージョンのSQS DLQをターゲットに設定し、メッセージの残留をAlarmで検知する |

どちらのAlarmも、SNSで通知する。

- SNSには、会社で許可されたメールの購読先だけを設定する。
- 業務Rejectとno-opは成功なので、通知の対象外である。
- メトリクスは、即時の通知や実行ごとに1通の通知を保証しない。通知は、Alarmの状態遷移によって送られる。
- DLQのメッセージは自動で再投入しない。原因を解消した後、会社側で手動で再実行する。
- 中断やTimeoutで世代itemが`RUNNING`のまま残った場合は、[状態遷移の表](#世代itemと状態遷移)の「古い`RUNNING`」に従って再実行する。変換ロックが残った場合は、[中断で残ったロックの復旧](#中断で残ったロックの復旧)に従う。

ログには、CSVの本文、検証エラーの全文、認証情報を出さない。Lambdaは操作ごとに、操作名、結果（`ok`または`error`）、エラーcode、inputId、attemptId、executionArn、Glue job run IDを1行のJSONで記録する。job run IDの記録に失敗した操作でも、`.sync`の完了結果にIDがあればログに出す。State Machineのログ（ERRORレベル、実行データを含めない）とGlueのログは、executionArnとjob run IDでLambdaのログと対応づける。ログとS3の保持期限、SNSの購読、実際の通知送信は、会社の設定とAWS 4の受け入れ確認で確定する。

## 検証の境界

| 段階 | 方法 | 確認する内容 |
|---|---|---|
| AWS 2 | AWS APIをモックした検証 | 条件付きの読み取りとコピー、サイズReject、SDKの失敗、二重受付、所有者条件、Retry、公開途中の失敗、再実行、ZIP内の共通コード |
| AWS 4 | 会社のAWS環境での実機確認 | IAM・EventBridge・Crawler・Glueの実連携、通知とDLQ、同一keyの更新、重複配信、失敗後の再実行、行欠落時の非公開、開始権限の拒否後の証跡確認と管理者復旧 |

固定入力の期待値は[samples/expected](../samples/expected/README.md)を使う。この期待値は仕様から導いたもので、実際のAzureで採取した値とは区別する。AWS 1のローカル比較によって、AWS 4の項目が実機で検証済みになったとは扱わない。
