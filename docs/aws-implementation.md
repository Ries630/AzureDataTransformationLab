# AWS版の配置と運用

AWS 2のコード、配置物の生成、実機操作をまとめる。処理の仕様は[AWS処理契約](aws-architecture.md)、段階と完成条件は[AWS計画](aws-learning-plan.md)を正とする。会社への一式ZIPはAWS 3で作成し、適用・サンプル投入・通知の確認はAWS 4で行う。会社の権限とサービス連携は未検証。

## コードと配置物

| 場所 | 責務 |
|---|---|
| [`functions/aws/handler.py`](../functions/aws/handler.py) | S3世代照合、共通検証、DynamoDBによる所有者管理、Crawler待機、公開と復旧 |
| [`functions/validator/validation.py`](../functions/validator/validation.py) | Azureと共有する検証規則。ZIP生成時にコピーしてSHA-256を照合 |
| [`workflows/aws/pipeline.asl.json`](../workflows/aws/pipeline.asl.json) | Standardの実行順序、待機、Retry、Glueの`.sync`と失敗処理 |
| [`glue/transform_orders.py`](../glue/transform_orders.py) | Sparkによる変換、未知列の保持、行数・cast欠落の検査、stagingへの保存 |
| [`infra/aws/pipeline`](../infra/aws/pipeline/README.md) | AWS専用root。コード配置、IAM、イベント、監視を管理 |
| [`scripts/aws/package.py`](../scripts/aws/package.py) | PEP 723のlockからLambda ZIPを生成し、展開後の実importを確認 |

Lambda ZIPは**指定CPUのLinux上**で生成する。既定はPython 3.14 / arm64であり、Mac上やWindows上で直接生成できない。WSLを使う場合もLinux側のCPUを照合する。x86_64で生成したZIPをarm64へ配置しない。

対応するLinux環境で、リポジトリのルートから実行する。

```bash
uv run scripts/aws/package.py /tmp/adtl-lambda.zip --architecture arm64 --python-version 3.14
```

出力先は新規ファイルとする。成功時はZIPの対象環境、依存一覧、共通検証コードとlockのhashが出力され、ZIP内の`package-manifest.json`にも記録される。会社側の配置では生成済みZIPを使い、通常は再ビルドしない。会社で別CPUが必要になった場合は、対応Linux上でZIPを再生成し、Terraformの`lambda_architecture`と一致させる。Python版を変える場合はコード・lockの互換性確認も必要。

MacなどからDockerを使う場合は、リポジトリを読み取り専用で渡し、出力用ディレクトリだけを書き込み可能にする。次はPython 3.14 / Linux arm64でZIP生成と実importを確認したイメージを固定した例。`REPOSITORY_ABSOLUTE_PATH`と`OUTPUT_ABSOLUTE_DIRECTORY`を実際の絶対パスへ置き換え、出力ディレクトリを先に作成する。

```bash
docker run --rm --platform linux/arm64 --mount type=bind,src=REPOSITORY_ABSOLUTE_PATH,dst=/src,readonly --mount type=bind,src=OUTPUT_ABSOLUTE_DIRECTORY,dst=/out -w /src ghcr.io/astral-sh/uv@sha256:7cf77f594be8042dab6daa9fe326f90962252268b4f120a7f5dccce4d947e6c1 uv run scripts/aws/package.py /out/lambda.zip
```

AWS APIモックの検査は`uv run --locked scripts/aws/test_pipeline.py`、Sparkの変換検査はJava 17を使って`uv run --locked scripts/aws/test_spark.py`で実行する。Spark検査はGlue 5.1に合わせたSpark/Python版で行うが、Glueサービス上の実行を確認するものではない。

## 会社での配置

[Terraform rootの手順](../infra/aws/pipeline/README.md)で会社の認証、アカウント、リージョン、stateと配置物を設定する。WindowsではPowerShell、WSLではbashから同じTerraformとAWS CLIの操作を使える。認証とツールを実行する環境を揃える。

会社環境で生成したplanを共有し、変更対象・費用・権限・保存期間を確認して承認を受けてから適用する。個人環境で作成した保存済みplanを会社へ持ち込まない。SNSの購読確認と実通知は、会社で許可された通知先で行う。

## サンプル投入と公開結果

以下の`BUCKET`、`PREFIX`、`STATE_MACHINE_ARN`、`STATE_TABLE`、`FUNCTION_NAME`は、適用結果と設定に置き換える。`PREFIX`は`data_prefix`の値で、新規専用bucketの既定値では空文字。CLI例はリポジトリのルートから実行する。

```bash
aws s3 cp samples/valid/orders_v1.csv s3://BUCKET/PREFIXlanding/orders_v1.csv
```

この投入はEventBridgeから実行を開始する。`samples/schema-evolution/orders_v2.csv`と`orders_v3.csv`で未知列の保持を確認し、不正入力は`samples/invalid/`から選ぶ。期待値と比較方法は[`samples/expected`](../samples/expected/README.md)を参照する。

公開済み結果はDynamoDBの世代itemを強い整合性で読み、`status=SUCCEEDED`と`publication.bucket`・`publication.key`を確認して取得する。S3の`output/`を一覧しただけでは公開済みと判定しない。`inputId`はStep Functionsの実行履歴から確認する。

```bash
aws dynamodb get-item --table-name STATE_TABLE --key file://input-key.json --consistent-read
```

`input-key.json`の内容:

```json
{"inputId":{"S":"INPUT_ID"}}
```

失敗したattemptのstagingや部分出力は調査用に残る。forced再実行中は世代itemが`RUNNING`となるため、新しい公開確定までその世代の結果を消費しない。

## 再実行

S3のHeadObjectで現在のETagを取得し、元のbucket・key・ETagを`retry.json`に記入する。ETagは内容のSHA-256として扱わない。異なるETagでの開始は別世代の実行になる。

```bash
aws s3api head-object --bucket BUCKET --key PREFIXlanding/orders_v1.csv
aws stepfunctions start-execution --state-machine-arn STATE_MACHINE_ARN --input file://retry.json
```

`retry.json`の内容:

```json
{"input":{"bucket":"BUCKET","key":"PREFIXlanding/orders_v1.csv","etag":"ETAG"}}
```

同一世代の成功・Rejectをやり直す場合だけ、トップレベルに`"force":true`を追加する。前の実行が終端状態になってから開始する。通常の重複イベントは再変換せず、既存結果へ参照を返す。StandardのRedriveは初期運用では使わない。

## 中断後のロック復旧

TimeoutやAbortでは共有変換ロックが残る場合がある。時刻だけでDynamoDBのitemを削除しない。まず`__transform_lock__`を強い整合性で読み、保存された所有`executionArn`、`attemptId`、`jobRunId`とpending情報を確認する。

```bash
aws dynamodb get-item --table-name STATE_TABLE --key file://lock-key.json --consistent-read
```

`lock-key.json`の内容:

```json
{"inputId":{"S":"__transform_lock__"}}
```

会社で許可された操作として、次の順で調査する。

1. 所有するStep Functions実行が終端状態であることを`describe-execution`で確認する。
2. Crawlerの状態と`LastCrawl`を`get-crawler`で確認する。必要なら`stop-crawler`で停止し、`READY`と対象crawlの終端を待つ。
3. 保存されたGlue job runを`get-job-run`で確認する。ID未記録の場合は`get-job-runs`の`--attempt_id`を照合する。必要なら`batch-stop-job-run`で停止し、対象job runの終端を待つ。
4. 所有者を`recover.json`へ記入し、Lambdaの復旧操作を実行する。

```bash
aws lambda invoke --function-name FUNCTION_NAME --cli-binary-format raw-in-base64-out --payload file://recover.json recover-result.json
```

`recover.json`の内容:

```json
{"operation":"recover","state":{"executionArn":"OWNER_EXECUTION_ARN","attemptId":"OWNER_ATTEMPT_ID"}}
```

Lambdaは所有者と旧実行・サービスの終了を再確認し、安全を確認できる場合だけ条件付きでロックを削除する。CLI終了コードだけで判断せず、`FunctionError`と`recover-result.json`を確認する。`RECOVERY_NOT_SAFE`で拒否された場合は調査を続ける。開始APIの応答消失などでpendingが残り、対象crawl/jobの終了を確認できなければロックを維持する。ロックitemの直接削除や開始APIの無条件再送で解除しない。未開始が証跡で確定した場合は、次の管理者による復旧を使う。

復旧後は新しいStep Functions実行を開始する。`recover`自体はCSVの再処理を開始せず、世代itemの成功状態を書き換えない。

### 開始が確実に拒否された場合の管理者復旧

開始前に保存したpending情報は、開始APIが権限拒否された場合にも残り得る。確認基準は[AWS処理契約の手動復旧条件](aws-architecture.md#実行状態排他と再実行)に従う。この操作の権限とCloudTrailの取得可否はAWS 4で確認する。

管理者はCloudTrailの`StartCrawler`または`StartJobRun`イベントを照合し、**対象の開始要求が確実に拒否され、サービスが開始されていない**ことを確認する。次をすべて満たす場合だけ、該当するpending一項目を変更する。

- 会社のアカウント・リージョン、実行主体、API名、要求時刻と自分用のCrawler名またはJob名が、旧実行の開始要求に一致する。Jobでは要求の`--attempt_id`も所有attemptと一致する。
- `errorCode`がアクセス拒否など開始不成立を確定できる拒否である。応答Timeout、ログ欠落、イベントが見つからないことを未開始の証拠にしない。再送があった場合は、該当するすべての開始要求について成功・結果不明が残っていない。
- 所有Step Functions実行が終端、Crawlerが`READY`、当該Jobの旧実行がすべて終端である。pending以外の稼働や結果不明を残さない。
- 強い整合性で読んだロックの`executionArn`・`attemptId`が対象の所有者と一致する。証跡と復旧操作を会社の方法で記録する。

例えば`StartJobRun`の拒否が確定した場合は、`lock-key.json`を前節の内容とし、`owner-pending.json`に現在の所有者を記入する。

```json
{":execution":{"S":"OWNER_EXECUTION_ARN"},":attempt":{"S":"OWNER_ATTEMPT_ID"},":yes":{"BOOL":true},":no":{"BOOL":false}}
```

```bash
aws dynamodb update-item --table-name STATE_TABLE --key file://lock-key.json --update-expression "SET gluePending = :no" --condition-expression "executionArn = :execution AND attemptId = :attempt AND gluePending = :yes" --expression-attribute-values file://owner-pending.json
```

Crawler開始の拒否が確定した場合は、上記の更新式と条件式の`gluePending`をどちらも`crawlerPending`に置き換え、一項目だけを更新する。条件不一致なら操作を止め、所有者を再調査する。両項目の一括変更や無条件の`false`設定は行わない。

更新後に前節の`recover`を再実行し、Lambda自身の安全確認を通してロックを解放する。CloudTrailの確認ができない、開始が拒否されたと断定できない、サービス終了を確認できない場合は、pendingとロックを維持する。
