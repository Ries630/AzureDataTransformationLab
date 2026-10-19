# AWS版の実装と会社学習環境への持ち込み計画

この文書は、Azureで学んだ検証・変換の処理をAWS向けに実装し、会社のAWS学習環境で構築するまでの段階と完成条件を定める。全体は[親Issue #30](https://github.com/Ries630/AzureDataTransformationLab/issues/30)、進捗は[AWS milestone](https://github.com/Ries630/AzureDataTransformationLab/milestone/2)で管理する。

| 段階 | 内容 | Issue | 状態 |
|---|---|---|---|
| [AWS 0](#aws-0-会社環境の条件確認) | 会社環境の条件確認 | [#31](https://github.com/Ries630/AzureDataTransformationLab/issues/31) | 確認キットを準備済み（[PR #44](https://github.com/Ries630/AzureDataTransformationLab/pull/44)）。会社での実行は未実施 |
| [AWS 1](#aws-1-共通部分とaws固有の契約を整理する) | 共通契約と比較基準 | [#32](https://github.com/Ries630/AzureDataTransformationLab/issues/32) | 完了 |
| [AWS 2](#aws-2-検証と変換のコードiacを作る) | コードとIaC | [#33](https://github.com/Ries630/AzureDataTransformationLab/issues/33) | 完了 |
| [AWS 3](#aws-3-持ち込み用bundleを作る) | 持ち込みZIP | [#34](https://github.com/Ries630/AzureDataTransformationLab/issues/34) | 完了 |
| [AWS 4](#aws-4-会社へ持ち込み構築を完了する) | 会社での構築と受け入れ確認 | [#35](https://github.com/Ries630/AzureDataTransformationLab/issues/35) | 完了（[実施記録](archive/AWS4-受け入れ記録.md)。DLQ障害試験、管理者復旧、同一keyの更新、行欠落時の非公開は未検証） |
| [AWS 5](#aws-5-azureと比較して学ぶ) | Azureとの比較と学習 | [#42](https://github.com/Ries630/AzureDataTransformationLab/issues/42) | 未着手 |

## 目的と完成条件

Azureで確かめた検証・変換の処理に、監視と再実行を加えてAWS向けに実装する。そのうえで、会社の学習環境で、Azureと同じサンプルと期待結果を使って学ぶ。個人側ではソースと配置用の成果物を作り、AWS実機での確認は会社の学習環境で行う。

構築完了の条件は次のとおりで、AWS 4で確かめる。

- 会社で許可された方法でコードと成果物を持ち込み、個人のGitHubへのログインに頼らずに配置できる。
- S3の`landing`へ置いたCSVから、イベントによって検証・変換が始まり、`output`へ出力される。
- 正常な入力、業務Reject、システム障害、スキーマ変更、再実行が、期待結果どおりに動く。
- Terraformと配置手順から、構築と更新を再現できる。

学習の完成条件は次のとおりで、AWS 5で確かめる。

- Azure版とAWS版の判定と出力を比べ、サービス固有の違いを説明できる。
- 後片付けの手順と、残すデータ・stateを説明できる。

会社の前提として、わかっていることと仮定していることを分けておく。

| 区分 | 内容 |
|---|---|
| わかっていること | 会社でAWS学習環境を利用でき、自分用のIAMアカウントが用意されている |
| 未確認 | IAMアカウントの紐づき先と実行権限 |
| 決めたこと | 持ち込みはファイル転送とし、コードと配置物を1つのZIPにまとめる |
| 仮定 | TerraformとAWS CLIを利用できる。会社での初回接続時に実行可否を確かめる |

この学習環境は、業務案件の本番仕様とは分けて扱う。

## 進め方と順序

最初の到達点は、会社の学習環境での構築完了とする。そのためにAWS 1〜4を先に進める。コード、Terraform、ZIPの作成はCodexが担当し、りーすさんの作業は会社環境での操作と承認に絞る。学習資料の作成とAzureとAWSの比較説明は、構築が終わってから行う。Azure Phase 5〜7は、会社の都合で進むAWS 4の完了を待たずに進める。

| 順序 | 対象 | 主な担当 | 内容 |
|---|---|---|---|
| 並行 | AWS 0 / #31 | りーすさん（会社） | Codexが用意した確認キットで、会社環境の条件を早めに確かめる |
| 1 | AWS 1 / #32 | Codex | Azure Phase 3・4の結果を比較基準として固定し、AWSの契約を決める |
| 2 | AWS 2 / #33 | Codex | 検証・変換・監視・再実行のコードとTerraform |
| 3 | AWS 3 / #34 | Codex | 会社へ持ち込むZIP |
| 4 | AWS 4 / #35 | りーすさん（会社）とCodex | 会社でのplan・適用・受け入れ確認。Codexはplanの確認と不具合の修正を担当する |
| 並行 | Azure Phase 5〜7 / #19〜#21 | 学習 | 監視、冪等性、再構築を[学習計画](learning-plan.md)に沿って進める。AWS 4の完了は待たない |
| 5 | AWS 5 / #42 | 学習 | Azureとの比較、サービス固有の違いの整理、後片付け |

比較の基準にするのは、Azure Phase 4（#18）まで完了した2026-10-12時点の`origin/main`（`1b064a4`）の検証規則、サンプル、実行結果である。AWS 1では、この入力、検証結果、最終出力を比較用データとして固定した。

比較の対象は、列と値、decimalの精度と丸め、日時のタイムゾーン、未知の列、行数、重複時の出力である。CSVの行順やサービス固有の実行IDは一致条件に含めない。詳しい規則は[アーキテクチャの比較基準](architecture.md#比較基準)を正とし、比較用データの側には複製しない。

監視と冪等性は、Azure Phase 5・6の結果を待たずに、AWS 1・2でAWSの仕組みに合わせて先に決める。Azure Phase 5・6では、その決定と比べながら学ぶ。

外部データの取得（[#28](https://github.com/Ries630/AzureDataTransformationLab/issues/28)）と対応表マスタ（[#29](https://github.com/Ries630/AzureDataTransformationLab/issues/29)）は、AzureとAWSの両方で当面の対象外とする。AWSでの構築が終わった後に、[後から追加する機能](#後から追加する機能)として扱う。

### りーすさんの作業

Codexは会社のAWSにも会社のPCにも接続できない。次の作業はりーすさんが行い、それ以外はCodexが進める。

| 時期 | 作業 |
|---|---|
| 承認済み | この計画と、AWS 1・2の詳細計画 |
| AWS 1〜2と並行 | 確認キットを会社へ持ち込んで実行し、秘密情報を除いた結果を共有する。不足する権限やstateの保存先を管理者へ依頼する |
| 各段階 | AWS 3の詳細計画の承認。各PRのマージ |
| AWS 3の後 | 許可された方法でZIPを会社へ転送する |
| AWS 4 | 環境値の設定、`terraform plan`の実行と結果の共有、適用の承認と実行、SNSメール購読の確認、サンプルの投入と結果の共有 |
| AWS 5 | 削除planの承認と後片付け |

会社で失敗した場合は、秘密情報を除いたログを持ち帰り、Codexが修正したZIPを作り直す。この往復を減らすため、権限とProviderを取得できるかどうかをAWS 0で先に確かめる。

## AWS 0: 会社環境の条件確認

会社環境の確認は、AWS 1〜2の実装と並行して早めに行う。コードと配置物の準備は、ファイル転送とTerraform・AWS CLIを使う構成を前提に進め、環境値は会社で設定する。

下表の未確認事項があっても、コードの作成は止めない。確定させる時期は事項によって異なり、配置物の形式に関わる条件はbundleを生成するまでに、実行対象と権限は会社での初回接続と適用の前に確定させる。

Codexは、会社で実行する読み取り専用の確認キットを先に用意する。キットは次を確かめ、結果を秘密情報なしで書き出す。リソースは作成しない。

- ツールの版
- 実行主体
- 必要な操作の権限シミュレーション（シミュレーション自体が拒否された場合は、管理者へ確認する項目として記録する）
- Providerを取得できるか
- 会社PCのOSとCPU

確認事項と、それぞれが実装や持ち込みに与える影響は次のとおりである。

| 確認事項 | 実装・持ち込みへの影響 |
|---|---|
| 利用アカウント、リージョン、利用期限、命名・タグの規則 | 対象の取り違えの防止と、削除の範囲 |
| Terraform・AWS CLIの実行可否、Providerの取得可否 | 個人側で生成するものと、会社側で実行するものの分担。uvとビルド手段は個人側で使い、会社には配置済みの成果物を渡す |
| IAMロールの作成、PassRole、S3・Lambda・Step Functions・Glue・EventBridge・CloudWatch・SNSの権限 | 自分で作る範囲と、管理者に用意してもらう範囲 |
| SSO・一時認証、permissions boundary、SCP、ネットワーク制限 | 実行主体、認可、Storageへのアクセス |
| Glue Catalog、KMSキー、S3、stateの保存先の提供状況 | 既存リソースを参照するか、新規に作成するか |
| 予算、通知先、保存期限、後片付けの責任者 | 実機で検証できる回数と、残すリソース |
| ファイルの転送先、依存の取得可否、会社PCのOS・CPU | ZIPの展開とProviderの配布。個人のGitHubへの接続を持ち込みの条件にしない |

会社での最初の確認は、ツールと既存の認証方法を使った読み取りから始める。

```bash
terraform version
aws --version
aws sts get-caller-identity
```

[`get-caller-identity`](https://docs.aws.amazon.com/cli/latest/reference/sts/get-caller-identity.html)で、実行主体とAWSアカウントを確かめる。リソースの作成、IAM、PassRoleの権限は別に照合し、不足していた操作だけを管理者への依頼範囲にする。認証には会社で用意された方式を使う。

完了条件は、会社への適用までに必要な操作を誰が行うかが決まり、実行対象、認証、権限を説明できることである。コードの作成中は、未確認の項目と仮定を記録しておく。権限の不足がわかった場合は、提供を受けてから該当する実機操作へ進む。

## AWS 1: 共通部分とAWS固有の契約を整理する

着手の条件は、この段階の実装計画が承認されていることである。Azure Phase 5〜7の完了は待たない。Terraform・AWS CLIの利用とファイル転送を前提に進め、AWS 0で確かめる環境値と実行権限は、配置の前に確認する。

CSVの検証には、既存の`functions/validator/validation.py`の`validate_csv(content, filename)`と、サンプル、純粋テストを再利用する。

- 検証規則の正は[CSV検証規則](architecture.md#csv検証規則)のまま変えない。
- 共通コードは既存の1か所で管理し、Lambda ZIPを生成するときにコピーする。Azure側のimportと配置は変更しない。
- 固定入力から導いた期待値は[samples/expected](../samples/expected/README.md)、共通の比較規則は[比較基準](architecture.md#比較基準)、AWS固有の契約は[AWS処理契約](aws-architecture.md)にある。

Azureに固有の部品は、AWSの部品に置き換える。

| Azure | AWS |
|---|---|
| HTTPの入口 | Lambdaの入口 |
| Managed Identity | 実行ロール |
| Blobの読み取り | S3の読み取り |
| 配置用ディレクトリ | Lambda ZIP |

Pythonの対象バージョンとCPUは、Azureの実行環境をそのまま引き継がず、AWSが対応する環境から選んでbundleに記録する。会社に固有の制約がわかった場合は、配置物を再生成する。

この段階では、次を決める。

- 入力S3のbucket・prefixと世代を限定し、検証後のコピーでも同じ世代を使う方法
- `VALID`・`INVALID`とシステム障害の区別。業務Rejectは正常終了、読み取り・変換・保存の失敗は処理の失敗とする
- ワークフローの中で受け渡す、入力の参照、オブジェクトの世代、検証結果の参照
- 重複配信、Retry、途中で失敗した後の再実行、出力の公開の方式。Azure Phase 6の結果を待たず、AWSの仕組みで決める
- システム障害を通知する条件。業務Rejectは通知しない

完了条件は、Azure Phase 3・4の比較用データに対する共通検証の結果が変わらず、AWS固有の入出力、世代、失敗、再実行の契約が文書になっていることである。

## AWS 2: 検証と変換のコード・IaCを作る

### 構成案

```text
学習用CSVをS3 landingへ配置（手動）
             ↓ Object Created
          EventBridge
             ↓
          検証・変換用Step Functions
             → Lambdaで共通CSV検証
                 ├─ INVALID → rejectedへ原本・結果を保存 → 正常終了
                 └─ VALID → validatedへ保存
                              → Glue Crawler／Data Catalog
                              → Glue ETL
                              → stagingで結果検査
                              → outputへ公開

システム障害 → CloudWatch Alarm → SNS（会社の通知先）
```

入口はAzureと同じく、`landing`へのCSVの配置とする。Glue ETLが後段の変換を担当する。Athenaによる取得は、[後から追加する機能](#後から追加する機能)として入口の前に足す。

Step Functionsは、Glue Jobの完了を待てるStandardを候補とする。[Glue連携](https://docs.aws.amazon.com/step-functions/latest/dg/connect-glue.html)の`.sync`を使い、開始APIが成功しただけでは処理が完了したと扱わない。Crawlerについても、開始した後に完了を確認し、Timeoutを設ける。

### 実装する範囲

1. **S3と権限**：自分用の入出力領域（`landing`・`validated`・`rejected`・`output`・staging）と実行ロールを定義する。会社が提供済みのリソースは参照するだけにし、会社側の共有基盤は作成・変更の対象から外す。
2. **Lambdaによる検証**：上限付きのS3読み取りと共通検証をつなぐ。検証結果の全文はS3に保存し、Step Functionsには判定と参照だけを渡す。CSVや大量のエラーを状態データに載せない。
3. **CrawlerとETL**：Crawlerは自分の学習用データだけを対象とし、他者のCatalogを更新しない。Glueの実装方式とバージョンは会社の条件に合わせ、Azureで確定した変換結果と比べる。
4. **実行制御**：EventBridgeの対象を、`landing`に置かれた完成したCSVに限定する。実行IDとS3の参照で履歴を対応づける。重複配信、公開途中の失敗、Retry、再実行は、AWS 1で決めた契約に従う。
5. **監視と費用**：検証・変換のシステム障害と業務Rejectを分ける。Glueの同時実行数とTimeout、ログと一時データの保持期間を決める。費用は会社の予算で見積もる。

### Terraformと配置物

- AWS用のrootは[`infra/aws/pipeline/`](../infra/aws/pipeline/README.md)に置き、Azure用のroot・stateから分離する。配置物の生成と運用は[実装手順](aws-implementation.md)にある。
- 実行対象のアカウントとリージョンを検査し、会社の認証方式とstateの保存先を使う。
- Lambda、Glue、ワークフローの定義はGitで管理し、配置用コードとインフラの更新手順を辿れるようにする。
- Pythonの依存はPEP 723と隣接するlockを正とし、Lambdaの対象環境に合わせてZIPを生成する。[Lambdaの配置仕様](https://docs.aws.amazon.com/lambda/latest/dg/python-package.html)に合わせて、Boto3を含む依存を固定して同梱する。
- Glue用コードの依存と配置方法はLambdaと分け、選んだGlueランタイムの条件を記録する。
- Providerはlockで固定する。会社でProviderを取得できない場合は、許可された配布方法で対象のOS・CPU用のmirrorを用意する。

完了条件は、会社で環境値を設定できるコードとTerraformがそろい、認証を使わないPRの検査で、共通検証、AWSアダプター、生成したZIP、IaCを確かめられることである。未確認の会社条件と仮定は記録しておく。実際のAPIの権限とサービス間の連携は、AWS 4で確かめる。

## AWS 3: 持ち込み用bundleを作る

[持ち込みZIPの手順](aws-bundle.md)に沿って、ファイル転送できる1つのZIPにまとめる。会社ではそれを展開し、環境値を設定する。

Lambda・Glueの配置物は個人側で生成し、会社でソースから再ビルドする手順は通常の流れに含めない。Providerは会社で取得するのを基本とし、取得できない場合に限り、対象のOS・CPU用のmirrorを同梱する。

| 同梱物 | 内容 |
|---|---|
| ソースとlock | 共通検証、AWS固有のコード、ワークフロー、Terraform、依存の固定情報 |
| 配置用の成果物 | Lambda ZIP、Glueスクリプト、必要な依存、許可された場合のProvider mirror |
| 学習データ | 架空のサンプルと配置手順、検証・変換の期待結果 |
| 環境設定の例 | アカウント、リージョン、既存リソース、命名、タグ、stateなど、会社で設定する項目 |
| 操作手順 | 前提の確認、init、plan、配置、実演、障害の調査、後片付け、途中で中断した後の再開 |
| manifest | ソースのcommit、対象のランタイムとCPU、依存の版、各成果物のSHA-256、検証結果 |

bundleは、許可したファイルだけから生成する。認証情報、個人の`.tfvars`、state、保存したplan、ログ、実データは含めない。会社の環境値は会社側で設定する。

完了条件は、空のディレクトリへ展開したbundleだけで、manifestの照合、配置物のimport、サンプルの検証、`terraform init -backend=false`と`terraform validate`までを再現できることである。オフラインでの利用が必要な場合は、ネットワークなしで確かめる。会社のbackendへの接続と実際のplanはAWS 4で行う。ローカルで確かめた範囲と、実機で未確認の範囲はmanifestに記録する。

## AWS 4: 会社へ持ち込み、構築を完了する

この段階は、会社で許可された端末と認証を使って、りーすさんが行う。コードの実装承認とは別に、会社環境への適用、サンプルの投入、通知の送信について承認を確かめる。Codexは共有されたplanと結果を読み、不具合があれば修正したZIPを作り直す。

1. 対象のアカウント、リージョン、実行ロールを照合する。
2. 会社の環境値とstateの保存先を設定し、planを作る。変更の対象、権限、費用、配置するコード、後片付けの対象を提示する。個人環境で保存したplanは使わない。
3. 承認されたplanを適用してコードを配置し、まず手動実行でLambdaとGlueを個別に確かめる。
4. イベント連携で、正常、Reject、スキーマ変更、障害、重複配信、途中失敗後の再実行を試し、実行履歴とS3の公開結果を照合する。開始の権限が拒否されてpendingが残るケースは、[管理者による復旧手順](aws-implementation.md#開始が確実に拒否された場合の管理者復旧)に沿って、CloudTrailの取得権限、未開始の証跡、所有者を条件にした更新とロックの解放を確かめる。
5. 通知先への送信が許可されていることを確かめたうえで、システム障害で通知が届き、業務Rejectでは届かないことを確かめる。

完了条件は、[構築完了の条件](#目的と完成条件)を実機で満たし、未検証の事項と、残っているリソース・費用を記録していることである。

## AWS 5: Azureと比較して学ぶ

AWS 4で構築が終わり、Azure Phase 5・6を終えた後に行う。

1. AWS 1で固定した比較用データと、AWSの判定・出力を比べる。
2. サービス固有の違いと、未検証の事項を整理する。
3. Azure Phase 5・6で学んだ監視と冪等性を、AWSで先に決めた方式と比べる。
4. 学習を終えたら、自分で作成した対象の削除planを確認し、承認を受けてから片付ける。共有リソースは削除対象に含めない。

完了条件は、[学習の完成条件](#目的と完成条件)を満たし、費用と、残すデータ・state・共有の依存を説明できることである。

## 後から追加する機能

次の機能は、AWS 4で構築が終わった後に、機能追加として扱う。再開するときに、AzureとAWSのどちらから追加するかと、Azure Phase 5〜7との順序を決め、AWS側のIssueを作る。

| 機能 | Azure | AWS側で追加する内容 |
|---|---|---|
| 外部データの取得 | [#28](https://github.com/Ries630/AzureDataTransformationLab/issues/28) | 取得用のStep FunctionsからAthenaで提供元のTableをSQLで抽出し、イベントの対象外へ保存する。そのうち既存の契約を満たす完成したCSVだけを`landing`へ公開する。0件の場合は正常終了とし、後段を起動しない |
| 対応表マスタ | [#29](https://github.com/Ries630/AzureDataTransformationLab/issues/29) | 対応表の保存先と、Glue ETLでのコード変換・参照する版の扱い。保存先のサービスは追加するときに選ぶ |

Athenaによる取得を追加するときは、次を引き継ぐ。

- 取得から公開までと、公開後の検証・変換を別のワークフローに分け、取得側から後段を直接起動しない。取得の失敗と後段の失敗を切り分けるためである。
- [AthenaのSELECT結果のCSV](https://docs.aws.amazon.com/athena/latest/ug/querying-finding-output-files.html)と、[Athena連携](https://docs.aws.amazon.com/step-functions/latest/dg/connect-athena.html)の`.sync`を候補にする。
- 別アカウントのTableは、会社から提供された共有方式で利用する。[Athenaのクロスアカウントアクセス](https://docs.aws.amazon.com/athena/latest/ug/lf-athena-limitations-cross-account.html)には、Catalogを共有する方式とLake Formationを使う方式があり、S3・KMSを含む権限も確認が必要である。2つ目のアカウントを使えない場合は、自分のアカウントの学習用Catalogで確かめ、クロスアカウントの認可は未検証として記録する。
- 対象行と除外行を含む固定サンプルと、通常の抽出と取得0件を再現するSQL・期待結果を用意する。
- AWS 0の確認事項に、Athenaの権限とworkgroup、提供元のサンプルTableの有無、別アカウントへの接続可否、Lake Formationの利用を加える。

## 判断と着手管理

AWS 1〜3は、Azure Phase 5〜7を待たずに、仮定とローカルで確かめられる完了条件を具体的にして着手する。未確認の会社の権限は、AWS 4の着手条件として残す。

AWS 1〜5は1段階ずつ着手する。着手の順序はGitHubのRelationshipsを正とする。詳細計画が必要なIssueには`ready-for-agent`を付けず、担当者を割り当てずに管理する。

構築を急ぐため、各段階の成果物は、コード、Terraform、手順書、比較用データを優先する。学習用の解説（`docs/tutorials/`に相当するもの）はAWS 5で書く。

ADRの候補は、入力の世代と出力の公開、冪等性の方式である。Athenaによる取得とGlue変換の役割分担や、クロスアカウントを模擬する場合の制約は、[後から追加する機能](#後から追加する機能)に着手するときに要否を判定する。判定は会社の条件とAzureでの検証結果を根拠に行い、必要な記録は承認済みの実装に含める。root・stateの分離やZIP生成の一般的な手順は、ADRではなく手順書で扱う。

本番案件のデータ量、抽出条件、共有方式、起動条件、後段への受け渡しは、案件資料で確認してから別に反映する。
