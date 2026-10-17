# AWS版の配置と運用

この文書は、AWS版の配置物を生成し、会社のAWS環境へ配置して動かすための手順をまとめる。処理の仕様は[AWS処理契約](aws-architecture.md)、段階と完成条件は[AWS計画](aws-learning-plan.md)を正とする。会社へ持ち込む一式のZIPは[AWS 3の持ち込み手順](aws-bundle.md)で作り、適用、サンプルの投入、通知の確認はAWS 4で行う。会社の権限とサービス連携は未検証である。

| 作業 | 参照する節 |
|---|---|
| Lambda ZIPを生成し、ローカルで検査する | [コードと配置物](#コードと配置物) |
| 会社のAWSへ適用する | [会社での配置](#会社での配置) |
| サンプルを投入し、公開された結果を取得する | [サンプル投入と公開結果](#サンプル投入と公開結果) |
| 失敗した入力や処理済みの入力をやり直す | [再実行](#再実行) |
| TimeoutやAbortの後、後続の実行がロック待ちで進まない | [中断後のロック復旧](#中断後のロック復旧) |
| 開始の権限が拒否され、pendingが残った | [管理者による復旧](#開始が確実に拒否された場合の管理者復旧) |

## コードと配置物

| 場所 | 責務 |
|---|---|
| [`functions/aws/handler.py`](../functions/aws/handler.py) | S3世代照合、共通検証、DynamoDBによる所有者管理、Crawler待機、公開と復旧 |
| [`functions/validator/validation.py`](../functions/validator/validation.py) | Azureと共有する検証規則。ZIP生成時にコピーしてSHA-256を照合 |
| [`workflows/aws/pipeline.asl.json`](../workflows/aws/pipeline.asl.json) | Standardの実行順序、待機、Retry、Glueの`.sync`と失敗処理 |
| [`glue/transform_orders.py`](../glue/transform_orders.py) | Sparkによる変換、未知列の保持、行数・cast欠落の検査、stagingへの保存 |
| [`infra/aws/pipeline`](../infra/aws/pipeline/README.md) | AWS専用root。コード配置、IAM、イベント、監視を管理 |
| [`scripts/aws/package.py`](../scripts/aws/package.py) | PEP 723のlockからLambda ZIPを生成し、展開後の実importを確認 |

### Lambda ZIPの生成

Lambda ZIPは、指定したCPUのLinux上で生成する。

- 既定はPython 3.14 / arm64である。MacやWindowsの上では直接生成できない。
- WSLを使う場合も、Linux側のCPUを照合する。
- x86_64で生成したZIPを、arm64のLambdaへ配置しない。

対応するLinux環境で、リポジトリのルートから実行する。出力先には新しいファイルを指定する。

```bash
uv run scripts/aws/package.py /tmp/adtl-lambda.zip --architecture arm64 --python-version 3.14
```

成功すると、ZIPの対象環境、依存の一覧、共通検証コードとlockのhashが表示され、ZIP内の`package-manifest.json`にも記録される。

会社側の配置では生成済みのZIPを使い、通常は再ビルドしない。会社で別のCPUが必要になった場合は、対応するLinux上でZIPを生成し直し、Terraformの`lambda_architecture`と一致させる。Pythonの版を変える場合は、コードとlockの互換性も確認する。

### MacからDockerで生成する場合

Dockerを使う場合は、リポジトリを読み取り専用で渡し、出力用のディレクトリだけを書き込み可能にする。次の例は、Python 3.14 / Linux arm64でZIPの生成と実際のimportを確認したイメージに固定している。`REPOSITORY_ABSOLUTE_PATH`と`OUTPUT_ABSOLUTE_DIRECTORY`を実際の絶対パスに置き換え、出力ディレクトリを先に作っておく。

```bash
docker run --rm --platform linux/arm64 --mount type=bind,src=REPOSITORY_ABSOLUTE_PATH,dst=/src,readonly --mount type=bind,src=OUTPUT_ABSOLUTE_DIRECTORY,dst=/out -w /src ghcr.io/astral-sh/uv@sha256:7cf77f594be8042dab6daa9fe326f90962252268b4f120a7f5dccce4d947e6c1 uv run scripts/aws/package.py /out/lambda.zip
```

### ローカルでの検査

AWS APIをモックした検査と、Sparkによる変換の検査は次で実行する。Spark検査にはJava 17が必要である。

```bash
uv run --locked scripts/aws/test_pipeline.py
uv run --locked scripts/aws/test_spark.py
```

Spark検査はGlue 5.1に合わせたSpark・Pythonの版で行うが、Glueサービス上での実行を確かめるものではない。

## 会社での配置

[Terraform rootの手順](../infra/aws/pipeline/README.md)に沿って、会社の認証、アカウント、リージョン、stateと配置物を設定する。WindowsのPowerShellからもWSLのbashからも同じTerraformとAWS CLIの操作を使えるが、認証とツールを実行する環境はどちらか一方に揃える。

planは会社環境で生成して共有し、変更対象・費用・権限・保存期間を確認して承認を受けてから適用する。個人環境で作成した保存済みplanは、会社へ持ち込まない。SNSの購読確認と実際の通知は、会社で許可された通知先で行う。

## サンプル投入と公開結果

コマンド中の値は、次のように置き換える。CLIの例はリポジトリのルートから実行する。`terraform output`はTerraform rootで実行する。

| 値 | 置き換える内容 |
|---|---|
| `BUCKET` | `terraform output`の`bucket_name` |
| `PREFIX` | `data_prefix`の値（`terraform output`の`data_prefix`）。新規の専用bucketでは既定値の空文字 |
| `STATE_MACHINE_ARN` | `terraform output`の`state_machine_arn` |
| `STATE_TABLE` | `terraform output`の`state_table` |
| `FUNCTION_NAME` | Lambdaの関数名。Terraformの変数`name`に設定した値 |

### CSVを投入する

```bash
aws s3 cp samples/valid/orders_v1.csv s3://BUCKET/PREFIXlanding/orders_v1.csv
```

この投入によって、EventBridgeが実行を開始する。ほかの入力は、確かめる内容に合わせて選ぶ。

| 確かめる内容 | 入力 |
|---|---|
| 正常な処理 | `samples/valid/orders_v1.csv` |
| 未知列の保持 | `samples/schema-evolution/orders_v2.csv`、`orders_v3.csv` |
| 業務Reject | `samples/invalid/`から選ぶ |

期待値と比較の方法は[`samples/expected`](../samples/expected/README.md)を参照する。

### 公開済みの結果を取得する

公開済みかどうかは、DynamoDBの世代itemを強い整合性で読んで判断する。`status=SUCCEEDED`であることと、`publication.bucket`・`publication.key`を確かめ、その参照から結果を取得する。S3の`output/`を一覧しただけでは、公開済みと判定しない。`inputId`は、Step Functionsの実行履歴か、Lambdaのログ（`/aws/lambda/`の後にTerraformの変数`name`の値を付けたロググループ）で確認する。

```bash
aws dynamodb get-item --table-name STATE_TABLE --key file://input-key.json --consistent-read
```

`input-key.json`の内容:

```json
{"inputId":{"S":"INPUT_ID"}}
```

失敗したattemptのstagingや部分的な出力は、調査用に残る。forced再実行の間は世代itemが`RUNNING`になるため、新しい公開が確定するまで、その世代の結果を消費しない。

## 再実行

やり直し方は、世代itemの状態によって変わる。

| 状況 | 操作 |
|---|---|
| 同じ世代のイベントが重複して届いた | 操作は不要。処理は再変換せず、既存の結果への参照を返す |
| 失敗した世代（`FAILED`、または中断で`RUNNING`のまま残った世代） | `force`を付けずに新しい実行を開始する |
| 成功またはRejectで終わった世代（`SUCCEEDED`・`REJECTED`） | トップレベルに`"force":true`を付けて新しい実行を開始する |

どちらの開始も、前の実行が終端状態になってから行う。StandardのRedriveは、初期運用では使わない。

開始の前に、S3のHeadObjectで現在のETagを取得し、元のbucket・key・ETagを`retry.json`に記入する。ETagは内容のSHA-256として扱わない。異なるETagで開始すると、別の世代の実行になる。

```bash
aws s3api head-object --bucket BUCKET --key PREFIXlanding/orders_v1.csv
aws stepfunctions start-execution --state-machine-arn STATE_MACHINE_ARN --input file://retry.json
```

`retry.json`の内容:

```json
{"input":{"bucket":"BUCKET","key":"PREFIXlanding/orders_v1.csv","etag":"ETAG"}}
```

## 中断後のロック復旧

TimeoutやAbortで実行が止まると、共有の変換ロックが残ることがある。ロックが残っている間、後続の実行はロックを待ち、待機の上限を超えると失敗する。

時刻だけを根拠にDynamoDBのitemを削除しない。まず`__transform_lock__`を強い整合性で読み、保存されている所有`executionArn`、`attemptId`、`jobRunId`とpendingの情報を確認する。

```bash
aws dynamodb get-item --table-name STATE_TABLE --key file://lock-key.json --consistent-read
```

`lock-key.json`の内容:

```json
{"inputId":{"S":"__transform_lock__"}}
```

続いて、会社で許可された操作として、次の順に調査する。

1. 所有するStep Functions実行が終端状態であることを`describe-execution`で確認する。
2. Crawlerの状態と`LastCrawl`を`get-crawler`で確認する。必要なら`stop-crawler`で停止し、`READY`と対象crawlの終端を待つ。
3. 保存されたGlue job runを`get-job-run`で確認する。IDはGlueの`.sync`が成功した後に記録されるため、Glueの実行中や失敗で止まった実行、Glue成功後に記録が失敗した実行や記録の前に止まった実行では未記録になる。ID未記録の場合は、`get-job-runs`の結果から、引数`--attempt_id`が所有attemptと一致するjob runを探す。必要なら`batch-stop-job-run`で停止し、対象job runの終端を待つ。一致するjob runが見つからない場合はLambdaの復旧操作も`RECOVERY_NOT_SAFE`で拒否されるため、[管理者復旧](#開始が確実に拒否された場合の管理者復旧)でpendingを解除する。
4. 所有者を`recover.json`へ記入し、Lambdaの復旧操作を実行する。

```bash
aws lambda invoke --function-name FUNCTION_NAME --cli-binary-format raw-in-base64-out --payload file://recover.json recover-result.json
```

`recover.json`の内容:

```json
{"operation":"recover","state":{"executionArn":"OWNER_EXECUTION_ARN","attemptId":"OWNER_ATTEMPT_ID"}}
```

Lambdaは、所有者と、旧実行・サービスの終了を改めて確かめ、安全を確認できた場合だけ条件付きでロックを削除する。結果は次のように確認する。

- CLIの終了コードだけで判断せず、`FunctionError`と`recover-result.json`を確認する。
- `RECOVERY_NOT_SAFE`で拒否された場合は、調査を続ける。
- 開始APIの応答が失われるなどしてpendingが残り、対象のcrawlやjobの終了を確認できない場合は、ロックが維持される。ロックitemを直接削除したり、開始APIを無条件に再送したりして解除しない。
- 開始されていないことが証跡で確定した場合は、次節の管理者による復旧を使う。

復旧した後は、新しいStep Functionsの実行を開始する。`recover`自体はCSVの再処理を開始せず、世代itemの成功状態も書き換えない。

### 開始が確実に拒否された場合の管理者復旧

処理は、CrawlerとGlue jobの開始APIを呼ぶ前に、変換ロックへpendingを記録する。開始APIの拒否を応答から確認できた場合は、処理がpendingを自動で戻す。一方、応答を受け取れなかった場合や、pendingを戻す前に実行が止まった場合は、開始が拒否されていてもpendingが残る。pendingが残っていると、対象のcrawlやjob runが存在しないため、Lambdaの`recover`はサービスの終了を確認できず、ロックを解放しない。

確認の基準は[AWS処理契約の手動復旧条件](aws-architecture.md#実行状態排他と再実行)に従う。この操作の権限と、CloudTrailを取得できるかどうかは、AWS 4で確認する。

管理者はCloudTrailの`StartCrawler`または`StartJobRun`イベントを照合し、**対象の開始要求が確実に拒否され、サービスが開始されていない**ことを確かめる。次をすべて満たす場合に限り、該当するpendingを1項目だけ変更する。

- 会社のアカウント・リージョン、実行主体、API名、要求時刻と自分用のCrawler名またはJob名が、旧実行の開始要求に一致する。Jobでは、要求の`--attempt_id`も所有attemptと一致する。
- `errorCode`が、アクセス拒否など開始の不成立を確定できる拒否である。応答のTimeout、ログの欠落、イベントが見つからないことを、未開始の証拠にしない。再送があった場合は、該当するすべての開始要求について、成功や結果不明が残っていない。
- 所有するStep Functions実行が終端、Crawlerが`READY`、当該Jobの旧実行がすべて終端である。pending以外の稼働や結果不明を残さない。
- 強い整合性で読んだロックの`executionArn`・`attemptId`が、対象の所有者と一致する。証跡と復旧操作を、会社の方法で記録する。

たとえば`StartJobRun`の拒否が確定した場合は、`lock-key.json`を前節の内容とし、`owner-pending.json`に現在の所有者を記入する。

```json
{":execution":{"S":"OWNER_EXECUTION_ARN"},":attempt":{"S":"OWNER_ATTEMPT_ID"},":yes":{"BOOL":true},":no":{"BOOL":false}}
```

```bash
aws dynamodb update-item --table-name STATE_TABLE --key file://lock-key.json --update-expression "SET gluePending = :no" --condition-expression "executionArn = :execution AND attemptId = :attempt AND gluePending = :yes" --expression-attribute-values file://owner-pending.json
```

Crawlerの開始の拒否が確定した場合は、上記の更新式と条件式の`gluePending`をどちらも`crawlerPending`に置き換え、1項目だけを更新する。条件が一致しなければ操作を止め、所有者を調べ直す。2つの項目をまとめて変更したり、無条件に`false`を設定したりしない。

更新した後に前節の`recover`をもう一度実行し、Lambda自身の安全確認を通してロックを解放する。CloudTrailを確認できない場合、開始が拒否されたと断定できない場合、サービスの終了を確認できない場合は、pendingとロックを維持する。
