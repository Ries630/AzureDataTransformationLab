# AWS4 受け入れ確認 実施記録（2026-10-15）

対象：[AWS4-受け入れ確認.md](AWS4-受け入れ確認.md)。事後に復元した記録で、試験中に取ったものではない。

## 構築

- 対象：会社の学習用AWSアカウント、東京リージョン（`ap-northeast-1`）。実行主体は会社が用意したIAMアカウント。
- 権限：管理者に`iam:TagRole`の追加を依頼した（見つかったことの4）。それ以外は既存の権限で足りた。
- state：[配置手順](../../infra/aws/pipeline/README.md)のとおりS3 backendに保存（`use_lockfile`によるロック）。
- plan・apply：会社でplanを作って確認し、同日に承認して適用し、成功した。その後`notification_email`を追加して再度plan・applyを行った。plan本体は持ち帰っていない。
- 配置したbundle：source commit `401afaae…`。GitHubがPR #56に作るマージ検査用のcommit（`f088a30`を`27ba49f`へマージしたもの）で、treeは`main`の`ebba005`と同一。#53・#56を含み、手順書の根拠`b31d034`より新しい。
- 後片付けの範囲：自分で作成したリソースだけ。共有リソースは含めない。

## 取得元と限界

- PowerShell履歴（PSReadLine）：実行したコマンドだけ。出力と時刻は残らない。
- bundle直下の保存ファイル：`lambda-smoke-result.json`、`glue-smoke-manifest.json`、`published-manifest.json` など。更新時刻が実行時刻の目安になる。
- AWS側の読み取りAPI：Step Functions、DynamoDB、Glue、CloudWatch、SQS、SNS、S3、Lambda。書き込みは行っていない。
- 表記：時刻はJST。アカウントIDは `<acct>` に伏せた。inputId・attemptId・JobRunIdは先頭12桁（全値はStep Functions履歴とDynamoDBにある）。8章の再実行のJobRunIdだけは全桁を次に記す。`jr_dca100ec51d112321316656eb3864bc1ac4b9816cb1f6b1b5d625ee48bc443b8`（2026-10-19にStep Functions履歴で確認）。

### 章別の取得元

| 章 | 取得元 |
|---|---|
| 1〜3、5のv2／v3 | 実行時の出力と照合して確定 |
| 4・6・7・8 | 記録作成時の取得元は章別に残っていない。2026-10-19にAWSの読み取りAPI（Step Functions、DynamoDB、Glue、CloudWatch、S3、SQS）で再取得し、実行ID・状態・時刻・inputId・attemptId・Glue run・Alarm・output配下・DLQの値が一致することを確認した。保存ファイル（`retry.json`、`failure.json`、`recover.json`、`rerun.json`、`published-manifest.json`）とも矛盾しない |
| 再取得できなかったもの | 8章の recover前のロックの中身（`crawlerStarted`など）。ロック項目が現在なく、保存ファイルにもない。SNS通知メールの受信（AWS側で確認できない） |

配置したLambdaの`CodeSha256`は、bundleの`manifest.json`記載の`dist/aws/lambda.zip`（sha256 `fda18576…`）と一致する（2026-10-19確認）。source commitの位置づけは[構築](#構築)に記す。

## 試験別の記録

| 章 | 試験 | 時刻 | 結果 | 主な識別子・根拠 |
|---|---|---|---|---|
| 1 | Lambda構成 | 実行時刻不明 | 合格 | Active／Successful／python3.14／arm64／handler.handler（AWSで再取得） |
| 1 | Lambda初期化 | 10:44 | 合格 | inputId `ce4a48ad3ef0`、attemptId `dce1af2bf420`、dataPrefix `""`。CLI出力は`StatusCode=200`、`ExecutedVersion=$LATEST`、`FunctionError`なし |
| 2 | Glue単体 | 10:45:33〜10:47:30 | 合格 | JobRunId `jr_68bf8ce61a9b`、`SUCCEEDED`、109秒。inputRows=3、outputRows=3、6列。ID/attemptはmanifestが今回の値 |
| 3 | Crawler単体 | 10:48:24〜 | 合格 | 対象`s3://adtl-demo-bucket/validated/`（`**/validation.json`除外）。2回目の`get-crawler`で`State=READY`、`LastCrawl.Status=SUCCEEDED`、StartTime 10:48:24。Glue Table `validated` が10:49:01に作成 |
| 4 | 正常入力 | 10:50:17〜10:54:06 | 合格 | 下記 |
| 5 | Reject | 11:00:06〜11:00:09 | 合格 | 下記 |
| 5 | v2 | 11:02:16〜11:05:17 | 合格 | 下記 |
| 5 | v3 | 11:05:53〜11:09:40 | 合格 | 下記 |
| 6 | 重複配送相当 | 11:13:57 | 合格 | 下記 |
| 7 | システム障害 | 11:16:41 | 合格 | 下記 |
| 7 | DLQ空確認 | 履歴あり | 合格（現在も0／0） | `adtl-demo-delivery-dlq` |
| 8 | 途中失敗と再実行 | 11:26:30〜11:52:14 | 合格 | 下記 |

### 4. 正常入力

- 入力：`landing/aws4-valid-20261015-101035.csv`、ETag `d381849c5ea1…`。
- Step Functions：`ad092248-e561-a5d2-d496-8970f779b3fa_fa4b0e75-…`、`SUCCEEDED`。
- inputId `6018aa9fea24`、attemptId `be906976bb3a`。Validateは`VALID`、errorCount=0、inputRows=3。
- Glue `jr_ffd6a66c7e27`、10:51:07〜10:53:10、`SUCCEEDED`。
- DynamoDB：`SUCCEEDED`、updatedAt 10:54:06。publicationは`output/6018…/be90…/manifest.json`。
- 出力：3行、sha256 `dac018dc5d14…`。単体のGlue出力と同一ハッシュ。期待値との差は日時の`.000`だけで、許容済みの差。
- staging：`staging/6018…`は残っていない（掃除済み）。

### 5. Rejectとスキーマ変更

| 入力 | Step Functions | 結果 | inputId | 備考 |
|---|---|---|---|---|
| invalid | `a91d58ec-…` | `SUCCEEDED`、`INVALID`、エラー5件、DynamoDB `REJECTED` | `1bfa4b1e9780` | rejected配下に原本とvalidation.json。Glueは起動していない。Failed Alarmなし |
| v2 | `c05d9c68-…` | `SUCCEEDED`、`VALID`、1行 | `142323cc681c` | Glue `jr_b96e2afdc7c0`、DynamoDB `SUCCEEDED` |
| v3 | `cc503dd0-…` | `SUCCEEDED`、`VALID`、1行 | `3e610c275781` | Glue `jr_74a6351a4aa1`、DynamoDB `SUCCEEDED` |

### 6. 重複配送相当

- 新実行 `60b4bb35-08ac-414a-b4ca-e880804ac63d`：`SUCCEEDED`、`accepted=false`、既存結果を返却。
- 同じinputId `6018aa9fea24`。新しいattemptId `49485a35d96e` が出るが公開先は変わらない。
- 11:13台にGlue runなし。DynamoDBのupdatedAtは10:54:06のまま。
- `retry.json` のETagは引用符付き（`head-object --output text`の出力）だったが、既存入力と判定された。

### 7. システム障害と通知

- 実行 `f86eb82d-8170-46aa-804c-1d60b9973764`：`FAILED`（`PIPELINE_FAILED`）、11:16:41〜11:16:42。
- DynamoDB：inputId `6cb76071245c` が `FAILED`。公開結果なし。Glueなし。
- `ExecutionsFailed`：11:17:09に`ALARM`、11:23:09に`OK`。
- SNS購読：メール1件、`Confirmed`。通知メールは11:17に受信（`ExecutionsFailed`のALARM 11:17:09と対応）。

### 5のv2/v3の出力比較

公開参照から取得したCSVを`samples/expected/transformed/drift/`と比較した。

| 入力 | 列 | 値 | 差 |
|---|---|---|---|
| v2 | 7列（`source_system`追加） | `SYSTEM_A`、税込14080 | `orderedAt`の`.000`のみ |
| v3 | 8列（`source_system`、`promotion_code`追加） | `SYSTEM_A`、`SUMMER2026`、税込14080 | `orderedAt`の`.000`のみ |

どちらも入力・出力1行で、manifestのinputRows／outputRowsも1。許容済みの差のみで合格。

### 8. 途中失敗後の再実行

| 項目 | 記録 |
|---|---|
| 入力 | `landing/aws4-abort-20261015-101035.csv`、ETag `d381849c5ea1…` |
| 中断した実行 | `ed5a0969-63d8-8aec-cb29-beb24bcf3bdc_f2e06593-…`、11:26:30〜11:27:58、`ABORTED` |
| inputId／attemptId | `eff50f6c5a87`／`cff3b71fc466` |
| Glue | `jr_414f1db7ffdb`、11:27:20開始、11:28:11 `STOPPED` |
| Crawler | 11:26:33開始、`SUCCEEDED`、現在`READY`。対象は中断attemptのvalidated配下 |
| Alarm | `ExecutionsAborted` が11:28:34に`ALARM`、11:34:34に`OK`。通知メールを11:28に受信 |
| ロック（recover前） | 11:34の`get-item`。所有executionArnは中断した実行、attemptId `cff3b71fc466`、ownerInputId `eff50f6c5a87`。`crawlerPending=true`、`gluePending=true`、`crawlerStarted=1792031193`（11:26:33、Crawler開始時刻と一致） |
| recover | 11:35:55に実行。`recover-result.json`は`{"recovered": true}` |
| 現在のロック | `__transform_lock__`項目なし（解放済み） |

再実行（同じbucket/key/ETagの手動開始、`force`なし）：

| 項目 | 記録 |
|---|---|
| 新しい実行 | `361a5a5d-8629-4b5e-b29e-53f49e3af2c5`、11:49:22〜11:52:14、`SUCCEEDED` |
| Glue | `jr_dca100ec51d…`（全桁は冒頭の表記欄）、11:50:12〜11:51:53、`SUCCEEDED` |
| DynamoDB | inputId `eff50f6c5a87` が `RUNNING` から `SUCCEEDED`（updatedAt 11:52:13）。attemptId `d4cbb5187c47` |
| 公開 | `output/eff50f6c…/d4cbb518…/manifest.json`。3行で期待値と一致（日時の`.000`のみ差） |
| 旧attempt | `cff3b71fc466`。公開参照と異なる。`output/`には出力がなく、`validated/`に原本とvalidation.jsonが残るだけ |
| ロック | `__transform_lock__`項目なし |

合格条件の判定（8-7）：

1. 旧実行 `ABORTED`、新実行 `SUCCEEDED`：合格。
2. `$Item.attemptId.S` と `$Published.attemptId` が一致（`d4cbb518…`）、`$OldAttempt`（`cff3b71f…`）とは異なる：合格。
3. `output/<inputId>/` は `d4cbb518…` だけ、公開CSVは4行（ヘッダ＋3行）：合格。
4. ロック項目なし（8-7の`get-item`は出力なし、AWS側でも不在を確認）：合格。

別実行：12:00:41に `9260467f-f099-487b-8772-f60fcba6eaf5` が開始され、`SUCCEEDED`、`accepted=false`で終了した。Glueは起動しておらず、DynamoDBの公開参照は11:52:13のまま。再実行コマンドが2回実行された結果で、6章と同じ重複扱いになっている。

## 未検証・未実施

- DLQ障害試験（配送拒否→DLQ→通知）。
- 開始権限拒否からの管理者復旧（証跡確認を含む）。
- 同一keyの更新（同じkeyへ内容の異なるCSVを置き、新しいETagとして扱われるか）。6章は同じkey・同じETagの重複配送だけを試した。
- 行欠落時の非公開（Glue出力の行数が入力と合わないときに公開しないこと）。

これらは[検証の境界](../aws-architecture.md#検証の境界)でAWS 4の実機確認に含まれるが、未検証のまま #35 を閉じる。1〜8章は、記録のうえ合格。1〜3章と5章のv2/v3は、実行時の出力と照合して確定した。10-14の失敗実行は修正済み（下記の2）。

## 試験中に見つかったこと

1. **Glue単体で `--data_prefix` が空だと失敗する。** 10-14 14:28の`jr_8164a5ea2d6e`が `argument --data_prefix: expected one argument` で`FAILED`。主因は、Glue側で空文字を必須引数として受けていたことで、#53（`ea694a2`）で修正済み。手順書2章の引数の書き方も合わせて直した。
2. **10-14の実行 `2342c2d1-…` は `FAILED`（`PIPELINE_FAILED`）で終わった。** Glue `jr_df8b0a3188b2`は`SUCCEEDED`だが実行は失敗し、`staging/1ee936…/966a4a…/`が残っている。Glue同期完了のIdの扱いの不具合で、#56（`f088a30`）で修正した。10-15にその修正版を適用して試験を始めた。本記録の1〜8章は修正版で実施している。
3. **`ExecutionsAborted` も通知対象。** 8章の停止でAlarmとなり、通知メールが届いた。文書の8章に追記した。
4. **初回のapply（10-13）は `iam:TagRole` の不足で4ロールの作成に失敗した。** 対象は`adtl-demo-lambda`・`glue`・`workflow`・`events`。ユーザーが所属するグループのカスタマーマネージドポリシー`RoleAndPolicie`が10-13 17:54（JST）にv7へ更新され、v6との差分は`iam:TagRole`の追加（2026-10-19にIAMの読み取りで確認）。その後のapplyは成功した（16件追加）。tag系で管理者に依頼した権限は、ポリシーの差分からは`iam:TagRole`だけ。依頼文面は確認していない。
5. **Crawlerが実行ごとに新しいTableを作る。** Crawlerの対象がattemptごとのvalidated配下に変わるため、Glue Database `adtl_demo`にTableが11件たまっている。AWS 5の比較と後片付けで扱う。

## 残っているもの

- S3 `adtl-demo-bucket`：landing 6、validated 15、rejected 2、output 8、staging 6、artifacts 1（オブジェクト数）。
- staging残：単体試験2件（10-14、10-15）と、10-14の失敗実行1件。
- DynamoDB `adtl-demo-state`：7件（`SUCCEEDED` 4、`REJECTED` 1、`FAILED` 2）。
- Glue Database `adtl_demo`：Table 11件（見つかったことの5）。
- SNS購読：メール1件（`Confirmed`）。
- Terraform state：S3 backendに残っている。
- 費用：無料枠内。保持期間は会社の規則を確認する。
