# AWS4：適用後の受け入れ確認（Windows PowerShell）

対象：Issue #35。手順の根拠は origin/main `b31d0346bdfbe8185c60af2d09e1cb5ebf797712`。
適用済みを前提に説明する手順。2026-10-15に実機で1〜8章を実施した結果は[AWS4-受け入れ記録.md](AWS4-受け入れ記録.md)にある（DLQ障害試験と開始権限拒否からの管理者復旧は未実施）。配置したbundleのsource commitは`401afaae…`で、上記の根拠commitとは別。会社planの実物レビューは未実施のまま。ZIP／CPUの照合は、配置済みLambdaの`CodeSha256`がmanifest記載の`lambda.zip`と一致し、CPUがarm64であることを2026-10-19に確認した。

会社でサンプル配置・Lambda/Crawler/Glue実行が許可されている範囲で実施する。障害通知の試験は通知送信も許可された後に行う。Glue実行には費用が発生する。学習の比較説明と #28・#29 は対象外。

## 0. 準備

展開したbundleのルート（`manifest.json`と`samples`がある場所）をPowerShellで開く。AWS CLIとTerraformはWindows側の会社認証を使う。以降のコマンドは同じPowerShellで順番に実行する。

```powershell
$ErrorActionPreference = "Stop"
$env:AWS_PAGER = ""
$Root = "infra/aws/pipeline"
$Bucket = terraform "-chdir=$Root" output -raw bucket_name
$Prefix = terraform "-chdir=$Root" output -raw data_prefix
$Crawler = terraform "-chdir=$Root" output -raw crawler_name
$Job = terraform "-chdir=$Root" output -raw glue_job_name
$Machine = terraform "-chdir=$Root" output -raw state_machine_arn
$Table = terraform "-chdir=$Root" output -raw state_table
$Topic = terraform "-chdir=$Root" output -raw notification_topic_arn
$Dlq = terraform "-chdir=$Root" output -raw delivery_dlq_url
# 現行IaCではLambda名とCrawler名が同じ。
$Function = $Crawler
$Region = $Machine.Split(":")[3]
$env:AWS_DEFAULT_REGION = $Region
$Tag = Get-Date -Format "yyyyMMdd-HHmmss"
# 出力ごと記録を残す。ログにはアカウントIDやメール等が含まれるため、共有前に伏せる。
Start-Transcript -Path ".\aws4-transcript-$Tag.txt" | Out-Null

# PowerShell 5.1でもJSONをUTF-8・BOMなしで保存する。
function Write-TestJson($Path, $Value) {
    $FullPath = Join-Path (Get-Location).Path $Path
    [System.IO.File]::WriteAllText(
        $FullPath, ($Value | ConvertTo-Json -Depth 30),
        (New-Object System.Text.UTF8Encoding($false))
    )
}
```

`$Bucket`が`adtl-demo-bucket`であることを確認する。`$Prefix`は空文字または会社で指定した専用prefix。state用の`adtl-demo-tfstate-bucket`にはCSVを置かない。

各AWS CLIが失敗した場合、その先のコマンドへ進めない。共有するログは会社の規則に従ってID・メール等を伏せる。

## 1. Lambdaの配置・初期化を確認する

```powershell
aws lambda get-function-configuration --function-name $Function --query '{State:State,Update:LastUpdateStatus,Runtime:Runtime,CPU:Architectures,Handler:Handler}'
```

期待：`Active`、`Successful`、`python3.14`、意図したCPU（今回はarm64）、`handler.handler`。

人工入力で初期化だけ呼ぶ。下記のCSVやETagは実在不要。

```powershell
Write-TestJson "lambda-smoke.json" @{
    operation = "initialize"
    event = @{ input = @{
        bucket = $Bucket
        key = "${Prefix}landing/lambda-smoke.csv"
        etag = "smoke-test"
    } }
    executionArn = "lambda-smoke-$Tag"
}
aws lambda invoke --function-name $Function --cli-binary-format raw-in-base64-out --payload file://lambda-smoke.json lambda-smoke-result.json
Get-Content -Raw .\lambda-smoke-result.json
```

期待：CLI応答に`FunctionError`がなく、結果に`input.inputId`と`attempt.attemptId`の64桁hash、正しい`dataPrefix`がある。

これはZIPのimport・環境変数・初期化の確認。S3読取、CSV検証、DynamoDB更新の権限は後段で確認する。この人工入力の戻り値を`acquire`や`validate`へ渡さない。CLI終了コードや`StatusCode=200`だけではLambda成功と判定しない。[AWS公式invoke仕様](https://docs.aws.amazon.com/cli/latest/reference/lambda/invoke.html)

## 2. Glueを単体で確認する

Step Functionsの実行とGlue jobが稼働していないことを会社のAWS画面で確認する。直接起動はDynamoDBロックを取得しないため、パイプラインと並行実行しない。

イベント対象外の`validated`へ架空CSVを置く。単体試験用のinputIdは64個の0、attemptIdは今回専用の値にする。

```powershell
$ManualId = "0" * 64
$ManualAttempt = "manual-smoke-$Tag"
$ManualSource = "${Prefix}validated/$ManualId/$ManualAttempt/source.csv"
$ManualStaging = "${Prefix}staging/$ManualId/$ManualAttempt/"
aws s3 cp .\samples\valid\orders_v1.csv "s3://$Bucket/$ManualSource"

Write-TestJson "glue-smoke-arguments.json" @{
    "--source_bucket" = $Bucket
    "--source_key" = $ManualSource
    "--staging_prefix" = $ManualStaging
    "--input_id" = $ManualId
    "--attempt_id" = $ManualAttempt
    "--data_prefix" = [string]$Prefix
}
$JobRun = aws glue start-job-run --job-name $Job --arguments file://glue-smoke-arguments.json --query JobRunId --output text
```

`--data_prefix`は空文字でも引数自体が必要。`$Prefix`が空だとterraform出力が`$null`になり、`[string]`で包まないとJSONに`null`が入り、Glueが`argument --data_prefix: expected one argument`で失敗する（実機で発生）。同じattemptを再利用せず、再試験では新しい`$Tag`とパスを使う。

以下を間隔を空けて実行し、今回のJobRunIdが終端状態になるまで待つ。

```powershell
aws glue get-job-run --job-name $Job --run-id $JobRun --query 'JobRun.{State:JobRunState,Error:ErrorMessage,Started:StartedOn,Completed:CompletedOn}'
```

`SUCCEEDED`後に結果を取得する。

```powershell
aws s3 cp "s3://$Bucket/${ManualStaging}manifest.json" .\glue-smoke-manifest.json
aws s3 cp "s3://$Bucket/${ManualStaging}part-00000.csv" .\glue-smoke-output.csv
Get-Content -Raw .\glue-smoke-manifest.json
Get-Content .\glue-smoke-output.csv
```

合格条件：manifestの`inputId`／`attemptId`が今回の値で、`inputRows=3`、`outputRows=3`。CSVは6列、データ3行。列は`orderId, customerId, amount, currency, orderedAt, taxIncludedAmount`、税込額は14080・4950・10780。

期待値は`samples/expected/transformed/standard/orders_v1.csv`。行順は一致条件に含めず、金額はDecimal値、日時は同じ日時として比較する。AWS出力の`.000`という小数秒表記だけで不一致にしない。

この段階の結果はstagingにあり、最終公開はまだ行われていない。単体用のvalidated/stagingデータは残るので記録する。

## 3. Crawlerを単体で確認する

初回適用直後のCrawlerは自分用`validated/`を対象にする。AWS Glue画面または`get-crawler`で対象を確認し、単体試験CSVが含まれるときに実行する。既にイベント試験を行ったCrawlerは直近attemptへ対象が変わっているため、下記だけで単体用CSVを確認したことにはならない。

```powershell
aws glue get-crawler --name $Crawler --query 'Crawler.{State:State,Targets:Targets,LastCrawl:LastCrawl}'
aws glue start-crawler --name $Crawler
```

同じ`get-crawler`を後で再実行し、`State=READY`、今回の`LastCrawl.StartTime`、`LastCrawl.Status=SUCCEEDED`を確認する。開始APIの成功だけでは完了と判定しない。自分用Glue Databaseに対象CSVのTableができていることをAWS画面で確認する。

Crawlerが完了してから次へ進む。

## 4. landingから正常入力のイベント連携を確認する

```powershell
$Key = "${Prefix}landing/aws4-valid-$Tag.csv"
aws s3 cp .\samples\valid\orders_v1.csv "s3://$Bucket/$Key"
```

Step Functions画面で対象State Machineの新しい実行を開き、入力のbucket/keyが今回のものか確認する。

期待する経路：`Initialize → Acquire → Validate → Lock → StartCrawler → PollCrawler → Glue → Publish → Release → CleanStaging → Done`。途中のChoice/Wait等も含まれる。数分かかる場合があるため、終端状態まで確認する。

合格条件：

- 実行が`SUCCEEDED`。Validate結果が`VALID`、`errorCount=0`、`inputRows=3`。
- 今回のCrawlerが成功し、履歴に記録されたGlue job runが`SUCCEEDED`。
- 履歴から今回の`inputId`を取得し、DynamoDBを強い整合性で読んで`status=SUCCEEDED`と`publication.bucket/key`を確認する。
- そのmanifestの`files`が示すCSVが単体確認と同じ期待値である。
- 成功attemptのstagingが掃除され、共有ロックが解放されている。

今回の実行ARNを画面からコピーすると、結果と公開参照をCLIでも確認できる。

```powershell
$ExecutionArn = "今回の実行ARNへ置換"
$Description = aws stepfunctions describe-execution --execution-arn $ExecutionArn | ConvertFrom-Json
$Result = $Description.output | ConvertFrom-Json
$InputId = $Result.input.inputId
Write-TestJson "input-key.json" @{ inputId = @{ S = $InputId } }
$Item = (aws dynamodb get-item --table-name $Table --key file://input-key.json --consistent-read | ConvertFrom-Json).Item
$Item.status.S
$PublishedBucket = $Item.publication.M.bucket.S
$PublishedKey = $Item.publication.M.key.S
aws s3 cp "s3://$PublishedBucket/$PublishedKey" .\published-manifest.json
$Published = Get-Content -Raw .\published-manifest.json | ConvertFrom-Json
aws s3 cp "s3://$PublishedBucket/$($Published.files[0].key)" .\published-output.csv
Get-Content .\published-output.csv
```

`describe-execution`で`SUCCEEDED`を確認した後に使う。**S3にoutputが見えるだけでは公開成功としない。公開の正はDynamoDBのSUCCEEDEDとpublication参照。**

実行が始まらない場合は、bucketのEventBridge有効化、ruleのbucket/prefix/suffix、ruleの有効状態、targetの権限、SQS DLQを順に確認する。同じファイルを何度も投入して原因を隠さない。

## 5. Rejectとスキーマ変更を確認する

一つずつ投入し、各実行の終了後に次へ進む。

```powershell
aws s3 cp .\samples\invalid\orders_invalid.csv "s3://$Bucket/${Prefix}landing/aws4-invalid-$Tag.csv"
```

期待：Validateが`INVALID`、エラー5件、DynamoDBが`REJECTED`。原本とvalidation.jsonがrejected配下に保存され、今回のinputIdのoutputは作られない。Step Functions自体は`SUCCEEDED`、Crawler/Glueへ進まない。業務Rejectによる障害通知はない。

```powershell
aws s3 cp .\samples\schema-evolution\orders_v2.csv "s3://$Bucket/${Prefix}landing/aws4-v2-$Tag.csv"
# v2の実行が終わった後にv3を投入する。
aws s3 cp .\samples\schema-evolution\orders_v3.csv "s3://$Bucket/${Prefix}landing/aws4-v3-$Tag.csv"
```

期待：双方VALID、入力・出力1行。v2の`source_system`、v3の`source_system`と`promotion_code`が値を保って出力される。対応する`samples/expected/transformed/drift/`のCSVと、DynamoDBの公開参照から取得したCSVを比較する。

## 6. 重複配送相当の確認

正常確認で成功した同じ`$Key`とETagを使い、手動で新しいStep Functions実行を始める。同じbucket/key/ETagを再配送した場合の処理を確認する試験で、EventBridgeが実際に二重配送した証拠ではない。

```powershell
$ETag = aws s3api head-object --bucket $Bucket --key $Key --query ETag --output text
Write-TestJson "retry.json" @{ input = @{ bucket = $Bucket; key = $Key; etag = $ETag } }
aws stepfunctions start-execution --state-machine-arn $Machine --input file://retry.json
```

期待：新実行は`SUCCEEDED`、Acquireの`accepted=false`、既存成功結果を返す。Validate/Crawler/Glueは動かず、DynamoDBの公開attemptとpublication参照が変わらない。前後のARN、Glue run数、DynamoDB参照を記録する。`force`は付けない。

## 7. システム障害と通知

メール購読を設定していなければ、SNS topicがあるだけではメールを受け取れない。最初の34 addが「新規bucket・メール購読なし」の構成なら、メール通知の受け入れは未完了として残す。会社で許可された宛先を`notification_email`へ設定し、新しいplanの確認・承認・適用、購読確認を行ってから通知試験を実施する。

通知送信が許可され、対象AlarmがOKに戻っている状態で、存在しない入力を手動開始してシステム障害を起こせる。以下のkeyが存在しないことを確認して使う。

```powershell
Write-TestJson "failure.json" @{ input = @{
    bucket = $Bucket
    key = "${Prefix}landing/aws4-does-not-exist-$Tag.csv"
    etag = "missing-object"
} }
aws stepfunctions start-execution --state-machine-arn $Machine --input file://failure.json
```

期待：ValidateのS3読取で失敗、Step Functionsが`FAILED`、DynamoDBが`FAILED`、公開結果なし。ExecutionsFailed AlarmがALARMになり、会社の許可された宛先へ通知される。この試験ではGlueは起動しない。

Alarmは状態遷移で通知するため、実行ごと一通を保証しない。Rejectの無通知は、別の障害と重ならない時間帯にAlarm履歴と実行履歴も照合する。

EventBridge配送失敗用のDLQが空であることも確認する。

```powershell
aws sqs get-queue-attributes --queue-url $Dlq --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible
```

空であることは通常配送の確認であり、配送拒否→DLQ→通知の障害試験を済ませた意味にはならない。

## 8. 途中失敗後の再実行

Glue実行中にパイプラインを中断しても、`recover`でロックを解放して同じ入力を新しいattemptで再実行できることを確認する。単純なmissing-object試験（7章）とは分ける。通知送信・停止操作が会社で許可されている範囲で行う。停止すると`ExecutionsAborted`のAlarmも通知対象になる。

### 8-1. 専用CSVを投入して実行を特定する

専用の正常CSVは`work/aws4-abort-test.csv`（`samples/valid/orders_v1.csv`と同じ3行）。

```powershell
$AbortKey = "${Prefix}landing/aws4-abort-$Tag.csv"
aws s3 cp .\work\aws4-abort-test.csv "s3://$Bucket/$AbortKey"
```

数秒後に、今回の実行ARNを取得する。他の実行が動いていないことが前提。

```powershell
$ExecutionArn = aws stepfunctions list-executions --state-machine-arn $Machine --status-filter RUNNING --query 'executions[0].executionArn' --output text
$ExecutionArn
```

### 8-2. Glueを待っている間に停止する

履歴の末尾が`Glue`状態に入っていること、Glue job runが`RUNNING`であることを確認してから停止する。ValidateからCrawler完了までに1〜2分かかる。Glueの完了前に止められなかった場合は成功してしまうので、新しい`$Tag`でやり直す。

```powershell
aws stepfunctions get-execution-history --execution-arn $ExecutionArn --reverse-order --max-results 5 --query 'events[].{Id:id,Type:type,Name:stateEnteredEventDetails.name}'
aws glue get-job-runs --job-name $Job --max-results 1 --query 'JobRuns[0].{Id:Id,State:JobRunState,Started:StartedOn}'
aws stepfunctions stop-execution --execution-arn $ExecutionArn --cause "AWS4 8章 中断試験"
```

### 8-3. 中断後の状態を確認する

```powershell
aws stepfunctions describe-execution --execution-arn $ExecutionArn --query '{Status:status,Stopped:stopDate}'
aws glue get-crawler --name $Crawler --query 'Crawler.{State:State,LastCrawl:LastCrawl.Status}'
aws glue get-job-runs --job-name $Job --max-results 1 --query 'JobRuns[0].{Id:Id,State:JobRunState,Completed:CompletedOn}'
```

- 実行が`ABORTED`であること。
- Crawlerが`READY`であること。
- 当該Glue job runが終端（`STOPPED`等）であること。まだ`RUNNING`や`STOPPING`なら終端まで待つ。`RUNNING`のままなら、当該runだけを会社の方法で停止する。停止する場合は次を使う。

```powershell
aws glue batch-stop-job-run --job-name $Job --job-run-ids "停止するJobRunId"
```

### 8-4. ロックを読んで記録する

`recover`の前に、ロックの中身を保存する。所有者の項目名と値は出力に従う。

```powershell
Write-TestJson "lock-key.json" @{ inputId = @{ S = "__transform_lock__" } }
aws dynamodb get-item --table-name $Table --key file://lock-key.json --consistent-read
```

- 項目がない場合はロックが残っていない。`recover`は不要で、8-6へ進む。
- 項目がある場合は、所有executionArn・attemptId・pendingを記録する。8-7の比較用に`$OldAttempt = "ロックの所有attemptId"`を設定する。
- ロックがない場合の`$OldAttempt`は、中断した実行の履歴にあるInitializeの出力`attempt.attemptId`から取る。

### 8-5. ロックが残っている場合だけrecoverする

所有者は8-4で保存した実値を使う。

```powershell
Write-TestJson "recover.json" @{
    operation = "recover"
    state = @{ executionArn = "ロックの所有実行ARN"; attemptId = "ロックの所有attemptId" }
}
aws lambda invoke --function-name $Function --cli-binary-format raw-in-base64-out --payload file://recover.json recover-result.json
Get-Content -Raw .\recover-result.json
```

`FunctionError`がなく`recovered=true`であること。`RECOVERY_NOT_SAFE`や開始結果不明で拒否された場合は、下の管理者復旧手順に従い、ここで止める。

### 8-6. 同じ入力で新しい実行を始める

元のbucket/key/ETagを使う。ETagは`head-object`の引用符を外す。`force`は付けない。StandardのRedriveは使わない。

```powershell
$AbortETag = (aws s3api head-object --bucket $Bucket --key $AbortKey --query ETag --output text).Trim('"')
Write-TestJson "rerun.json" @{ input = @{ bucket = $Bucket; key = $AbortKey; etag = $AbortETag } }
$ExecutionArn = aws stepfunctions start-execution --state-machine-arn $Machine --input file://rerun.json --query executionArn --output text
```

数分後、`describe-execution`で`SUCCEEDED`になるまで待つ。

```powershell
aws stepfunctions describe-execution --execution-arn $ExecutionArn --query '{Status:status,Stopped:stopDate}'
```

### 8-7. 合格を確認する

4章の`describe-execution`から`published-output.csv`までのコマンドを、この`$ExecutionArn`で実行する。続けて次を実行する。4章のコマンドは新実行の状態と公開CSVを見るだけなので、旧attemptとの比較・出力の重複・ロックは下記で補う。

```powershell
# 公開参照のattemptが新しいこと。$OldAttemptは8-4で記録した値。
$Item.attemptId.S
$Published.attemptId
$OldAttempt
# このinputIdの出力がいくつのattemptにあるか。
aws s3 ls "s3://$Bucket/${Prefix}output/$InputId/"
# 公開CSVの行数（ヘッダ込みで4）。
(Get-Content .\published-output.csv | Measure-Object -Line).Lines
# ロックが解放されていること（項目なしなら`Item`が出ない）。
aws dynamodb get-item --table-name $Table --key file://lock-key.json --consistent-read
```

合格条件：

1. 旧実行が`ABORTED`、新実行が`SUCCEEDED`。
2. DynamoDBの`status`が`SUCCEEDED`で、`$Item.attemptId.S`と`$Published.attemptId`が一致し、`$OldAttempt`とは異なる。
3. `output/<inputId>/`の下に新attemptだけがあり、公開CSVが期待値と同じ3行。
4. ロック項目がない。

旧attemptの部分出力が別の場所に残っていても、公開済みとは扱わない。

`RECOVERY_NOT_SAFE`や開始結果不明で拒否された場合はロックを直接削除しない。[管理者復旧手順](https://github.com/Ries630/AzureDataTransformationLab/blob/b31d0346bdfbe8185c60af2d09e1cb5ebf797712/docs/aws-implementation.md#開始が確実に拒否された場合の管理者復旧)に従う。

## 記録して残すもの

コマンドの出力は0章の`Start-Transcript`が`aws4-transcript-<Tag>.txt`に残す。時刻と識別子は次の項目を試験ごとに表へまとめる（実例は[AWS4-受け入れ記録.md](AWS4-受け入れ記録.md)）。

試験ごとに入力key/ETag、Step Functions ARNと終端状態、inputId/attemptId、Crawler開始時刻、Glue JobRunId、DynamoDB状態とpublication参照、出力行数・比較結果、通知の有無を記録する。未実施のDLQ障害試験、開始権限拒否からの管理者復旧等は未検証として区別する。

残るもの：Terraform管理リソース、state/lock保存先、単体試験のvalidated/staging、統合試験のlanding/validated/rejected/output、DynamoDB状態、ログ、SNS購読。保持期間と会社の費用を確認し、後片付けは別の削除planを承認して行う。

仕様の正： [配置・運用](https://github.com/Ries630/AzureDataTransformationLab/blob/b31d0346bdfbe8185c60af2d09e1cb5ebf797712/docs/aws-implementation.md)、[AWS処理契約](https://github.com/Ries630/AzureDataTransformationLab/blob/b31d0346bdfbe8185c60af2d09e1cb5ebf797712/docs/aws-architecture.md)、[固定期待値](https://github.com/Ries630/AzureDataTransformationLab/blob/b31d0346bdfbe8185c60af2d09e1cb5ebf797712/samples/expected/README.md)。
