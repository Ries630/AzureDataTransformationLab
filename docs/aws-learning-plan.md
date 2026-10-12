# AWS版の実装と会社学習環境への持ち込み計画

ステータス: AWS 0の確認キットは[PR #44](https://github.com/Ries630/AzureDataTransformationLab/pull/44)で準備、AWS 1の契約と比較基準を整理済み、AWS 2のコードとIaCはマージ済み、AWS 3の持ち込みZIPを準備中。会社での実機操作は未着手。全体は[親Issue #30](https://github.com/Ries630/AzureDataTransformationLab/issues/30)、進捗は[AWS milestone](https://github.com/Ries630/AzureDataTransformationLab/milestone/2)で管理する。会社環境での構築完了を優先し、Azure Phase 5〜7と比較・学習は構築の後に行う。

| 段階 | Issue |
|---|---|
| AWS 0: 環境確認 | [#31](https://github.com/Ries630/AzureDataTransformationLab/issues/31) |
| AWS 1: 共通契約・比較基準 | [#32](https://github.com/Ries630/AzureDataTransformationLab/issues/32) |
| AWS 2: コード・IaC | [#33](https://github.com/Ries630/AzureDataTransformationLab/issues/33) |
| AWS 3: 持ち込みZIP | [#34](https://github.com/Ries630/AzureDataTransformationLab/issues/34) |
| AWS 4: 会社での構築と受け入れ確認 | [#35](https://github.com/Ries630/AzureDataTransformationLab/issues/35) |
| AWS 5: Azureとの比較と学習 | [#42](https://github.com/Ries630/AzureDataTransformationLab/issues/42) |

## 目的と完成条件

Azureで検証した検証・変換の処理経路に、監視と再実行を加えてAWS向けに実装し、会社の学習環境で同じサンプルと期待結果を使って学ぶ。個人側ではソースと配置用成果物を作成し、AWS実機での確認は会社の学習環境で行う。

構築完了の条件は次のとおりとし、AWS 4で確認する。

- 会社で許可された方法でコードと成果物を持ち込み、個人GitHubへのログインに依存せず配置できる。
- S3 `landing`へ配置したCSVからイベントで検証・変換が始まり、`output`へ出力される。
- 正常入力、業務Reject、システム障害、スキーマ変更、再実行が期待結果どおりに動く。
- Terraformと配置手順から構築・更新を再現できる。

学習の完成条件は次のとおりとし、AWS 5で確認する。

- Azure版とAWS版の判定・出力を比較し、サービス固有の違いを説明できる。
- 後片付けの手順と、残すデータ・stateを説明できる。

会社でAWS学習環境が利用可能で、自分用のIAMアカウントが用意されている。IAMの紐づき先と実行権限は未確認。持ち込みはファイル転送とし、コードと配置物を一つのZIPにまとめる。Terraform・AWS CLIは利用可能と仮定して準備し、会社での初回接続時に実行可否を確認する。業務案件の本番仕様とは分けて扱う。

## 進め方と順序

AWS 1〜4を先に進め、会社の学習環境での構築完了を最初の到達点にする。コード・Terraform・ZIPの作成はCodexが担当し、りーすさんの作業は会社環境での操作と承認に絞る。学習資料の作成、Azure Phase 5〜7、AzureとAWSの比較説明は、構築完了後に行う。

| 順序 | 対象 | 主な担当 | 内容 |
|---|---|---|---|
| 並行 | AWS 0 / #31 | りーすさん（会社） | Codexが用意した確認キットで、会社環境の条件を早めに確かめる |
| 1 | AWS 1 / #32 | Codex | Azure Phase 3・4の結果を比較基準に固定し、AWSの契約を決める |
| 2 | AWS 2 / #33 | Codex | 検証・変換・監視・再実行のコードとTerraform |
| 3 | AWS 3 / #34 | Codex | 会社へ持ち込むZIP |
| 4 | AWS 4 / #35 | りーすさん（会社）とCodex | 会社でのplan・適用・受け入れ確認。Codexはplanの確認と不具合の修正 |
| 5 | Azure Phase 5〜7 / #19〜#21 | 学習 | 監視、冪等性、再構築を[学習計画](learning-plan.md)に沿って進める |
| 6 | AWS 5 / [#42](https://github.com/Ries630/AzureDataTransformationLab/issues/42) | 学習 | Azureとの比較、サービス固有の違いの整理、後片付け |

2026-10-12時点の`origin/main`（`1b064a4`）では、Azure Phase 4（#18）までが完了している。AWS 1はこの時点の検証規則・サンプル・実行結果を比較基準にする。監視と冪等性はAzure Phase 5・6の結果を待たず、AWS 1・2でAWSの機構に合わせて先に決める。Azure Phase 5・6では、その決定と比べながら学ぶ。

外部データ取得 [#28](https://github.com/Ries630/AzureDataTransformationLab/issues/28) と対応表マスタ [#29](https://github.com/Ries630/AzureDataTransformationLab/issues/29) は、AzureとAWSの両方で当面の対象外とする。AWSの構築完了後に、[後から追加する機能](#後から追加する機能)として扱う。

AWS 1で、Azure Phase 3・4の入力、検証結果、最終出力を比較用データとして固定する。列と値、decimalの精度・丸め、日時のタイムゾーン、未知列、行数、重複時の出力を比較対象にし、CSVの行順やサービス固有の実行IDは一致条件に含めない。詳細な規則は[アーキテクチャ](architecture.md)を参照し、比較用データに複製しない。

### りーすさんの作業

Codexは会社のAWSと会社PCに接続できない。次の作業はりーすさんが行い、それ以外はCodexが進める。

| 時期 | 作業 |
|---|---|
| 承認済み | この計画とAWS 1・2の詳細計画 |
| AWS 1〜2と並行 | 確認キットを会社へ持ち込んで実行し、秘密情報を除いた結果を共有する。不足する権限やstate保存先を管理者へ依頼する |
| 各段階 | AWS 3の詳細計画の承認。各PRのマージ |
| AWS 3の後 | 許可された方法でZIPを会社へ転送する |
| AWS 4 | 環境値の設定、`terraform plan`の実行と結果の共有、適用の承認と実行、SNSメール購読の確認、サンプル投入と結果の共有 |
| AWS 5 | 削除planの承認と後片付け |

会社で失敗した場合は、秘密情報を除いたログを持ち帰り、Codexが修正したZIPを作り直す。往復の回数を減らすため、AWS 0で権限とProvider取得を先に確かめる。

## AWS 0: 会社環境の条件確認

会社環境の確認はAWS 1〜2の実装と並行し、早めに行う。ファイル転送とTerraform・AWS CLIを使う構成でコードと配置物の準備を進め、環境値は会社で設定する。下表の未確認事項は、コード作成を一律に止める条件にはしない。配置物の形式を変える条件はbundle生成時、実行対象と権限は会社での初回接続・適用前に確定する。

Codexは、会社で実行する読み取り専用の確認キットを先に用意する。キットはツールの版、実行主体、必要な操作の権限シミュレーション、Providerの取得可否、会社PCのOS・CPUを確かめ、結果を秘密情報なしで書き出す。リソースは作成しない。権限シミュレーション自体が拒否された場合は、管理者へ確認する項目として記録する。

| 確認事項 | 実装・持ち込みへの影響 |
|---|---|
| 利用アカウント、リージョン、利用期限、命名・タグの規則 | 対象の取り違え防止と削除範囲 |
| Terraform・AWS CLIの実行可否、Provider取得可否 | 個人側で生成するものと会社側で実行するもの。uvとビルド手段は個人側で使い、会社には配置済み成果物を渡す |
| IAMロール作成、PassRole、S3・Lambda・Step Functions・Glue・EventBridge・CloudWatch・SNSの権限 | 自分で作る範囲と管理者に用意してもらう範囲 |
| SSO／一時認証、permissions boundary、SCP、ネットワーク制限 | 実行主体、認可、Storageへのアクセス |
| Glue Catalog、KMSキー、S3、state保存先の提供状況 | 既存リソースの参照と新規作成の区別 |
| 予算、通知先、保存期限、後片付けの責任者 | 実機検証の回数と残すリソース |
| ファイル転送先、依存の取得可否、会社PCのOS・CPU | ZIPの展開とProviderの配布。個人GitHubへの接続を持ち込み条件にしない |

会社での最初の確認は、ツールと既存の認証方法を使った読み取りから始める。

```bash
terraform version
aws --version
aws sts get-caller-identity
```

[`get-caller-identity`](https://docs.aws.amazon.com/cli/latest/reference/sts/get-caller-identity.html)で実行主体とAWSアカウントを確認する。リソース作成・IAM・PassRoleの権限は別に照合し、不足した操作だけ管理者への依頼範囲にする。認証は会社で用意された方式を使う。

完了条件は、会社への適用までに必要な操作を誰が行うかが決まり、実行対象・認証・権限を説明できること。コード作成中は未確認項目と仮定を残し、権限不足が判明した場合は提供を受けてから該当する実機操作へ進む。

## AWS 1: 共通部分とAWS固有の契約を整理する

着手条件はこの段階の実装計画の承認とする。Azure Phase 5〜7の完了は待たない。Terraform・AWS CLIの利用とファイル転送を前提に進め、AWS 0の環境値と実行権限は配置前に確認する。

既存の`functions/validator/validation.py`の`validate_csv(content, filename)`とサンプル・純粋テストを再利用する。検証規則の正は[CSV検証規則](architecture.md#csv検証規則)に保つ。共通コードは既存の一か所で管理し、Lambda ZIP生成時にコピーするため、Azureのimport・配置は変更しない。固定入力の派生期待値は[samples/expected](../samples/expected/README.md)、共通の[比較基準](architecture.md#比較基準)とAWS固有の[AWS処理契約](aws-architecture.md)を参照する。

Azure固有のHTTP入口、Managed Identity、Blob読み取り、配置用ディレクトリは、Lambda入口、実行ロール、S3読み取り、Lambda ZIPへ置き換える。Pythonの対象バージョンとCPUはAWSの対応環境から選び、bundleに記録する。会社固有の制約が判明した場合は配置物を再生成する。Azureの実行環境をそのまま引き継がない。

この段階で次を決める。

- 入力S3のbucket・prefixと世代を限定し、検証後のコピーでも同じ世代を使う方法。
- `VALID`・`INVALID`とシステム障害の区別。業務Rejectは正常終了、読み取り・変換・保存の失敗は処理失敗とする。
- ワークフローで渡す入力参照、オブジェクト世代、検証結果の参照。
- 重複配送、Retry、途中失敗後の再実行、出力公開の方式。Azure Phase 6の結果を待たず、AWSの機構で決める。
- システム障害の通知条件。業務Rejectは通知しない。

完了条件は、Azure Phase 3・4の比較用データに対する共通検証が変わらず、AWS固有の入出力・世代・失敗・再実行の契約が明文化されていること。

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

入口はAzureと同じく、`landing`へのCSV配置とする。Glue ETLは後段の変換を担当する。Athenaによる取得は[後から追加する機能](#後から追加する機能)で入口の前に足す。

Step Functionsは、Glue Jobの完了を待つ処理に対応するStandardを候補とする。[Glue連携](https://docs.aws.amazon.com/step-functions/latest/dg/connect-glue.html)の`.sync`を使い、開始APIの成功を処理完了と扱わない。Crawlerの開始後も完了確認とTimeoutを設ける。

### 実装する範囲

1. **S3と権限**: 自分の入出力領域（`landing`・`validated`・`rejected`・`output`・staging）と実行ロールを定義する。提供済みのリソースは参照し、会社側の共有基盤は作成・変更対象から外す。
2. **Lambda検証**: 上限付きのS3読み取りと共通検証を接続する。検証結果の全文はS3へ保存し、Step Functionsには判定と参照を渡す。CSVや大量のエラーを状態データへ載せない。
3. **Crawler・ETL**: Crawlerは学習用の自分のデータだけを対象とし、他者のCatalogを更新しない。Glueの実装方式・バージョンは会社の条件に合わせ、Azureで確定した変換結果と比較する。
4. **実行制御**: EventBridgeは`landing`の完成CSVに限定する。実行IDとS3参照で履歴を対応付ける。重複配送、公開途中の失敗、Retry、再実行はAWS 1で決めた契約で扱う。
5. **監視・費用**: 検証・変換のシステム障害と業務Rejectを分ける。Glueの同時実行・Timeout、ログ・一時データの保持期間を定める。費用は会社の予算で見積もる。

### Terraformと配置物

- AWS用rootは[`infra/aws/pipeline/`](../infra/aws/pipeline/README.md)に置き、Azure用root・stateから分離する。配置物の生成と運用は[実装手順](aws-implementation.md)を参照する。
- 実行対象アカウント・リージョンを検査し、会社の認証方式とstate保存先を使う。
- Lambda・Glue・ワークフロー定義はGit管理し、配置用コードとインフラの更新手順を辿れるようにする。
- Python依存はPEP 723と隣接lockを正とし、Lambdaの対象環境に合わせてZIPを生成する。[Lambdaの配置仕様](https://docs.aws.amazon.com/lambda/latest/dg/python-package.html)に合わせ、Boto3を含む依存を固定して同梱する。
- Glue用コードの依存と配置方法はLambdaと分け、選択するGlueランタイムの条件を記録する。
- Providerはlockで固定する。会社で取得できない場合は、許可された配布方法で対象OS・CPU用のmirrorを用意する。

完了条件は、環境値を会社で設定できるコードとTerraformが揃い、認証不要のPR検査で共通検証・AWSアダプター・生成ZIP・IaCを確認できること。未確認の会社条件と仮定を記録し、実APIの権限とサービス連携はAWS 4で確認する。

## AWS 3: 持ち込み用bundleを作る

[持ち込みZIPの手順](aws-bundle.md)に沿ってファイル転送できる一つのZIPへまとめ、会社では展開して環境値を設定する。Lambda・Glueの配置物は個人側で生成し、会社でのソース再ビルドを通常手順に含めない。Providerは会社で取得する手順を基本とし、取得できない場合に対象OS・CPU用のmirrorを同梱する。

| 同梱物 | 内容 |
|---|---|
| ソースとlock | 共通検証、AWS固有コード、ワークフロー、Terraform、依存の固定情報 |
| 配置用成果物 | Lambda ZIP、Glueスクリプト、必要な依存、許可された場合のProvider mirror |
| 学習データ | 架空サンプルと配置手順、検証・変換の期待結果 |
| 環境設定の例 | アカウント・リージョン・既存リソース・命名・タグ・stateを会社で設定する項目 |
| 操作手順 | 前提確認、init、plan、配置、実演、障害調査、後片付け、途中中断からの再開 |
| manifest | ソースcommit、対象ランタイム・CPU、依存版、各成果物のSHA-256、検証結果 |

bundleは許可したファイルから生成し、認証情報、個人の`.tfvars`、state、保存済みplan、ログ、実データを含めない。会社の環境値は会社側で設定する。

完了条件は、別の空ディレクトリへ展開したbundleだけで、manifest照合、配置物のimport、サンプル検証、`terraform init -backend=false`と`terraform validate`まで再現できること。オフライン利用が必要な場合はネットワークなしで確認する。会社のbackendへの接続と実planはAWS 4で行い、ローカルで確認した範囲と実機未確認の範囲をmanifestへ記録する。

## AWS 4: 会社へ持ち込み、構築を完了する

この段階は会社の許可された端末と認証で、りーすさんが実施する。コードの実装承認とは別に、会社環境への適用、サンプル投入、通知の送信の承認を確認する。Codexは共有されたplanと結果を読み、不具合があれば修正したZIPを作り直す。

1. 持ち込み後にSHA-256と対象アカウント・リージョン・実行ロールを照合する。
2. 会社の環境値とstate保存先を設定してplanを作る。変更対象、権限、費用、配置するコード、後片付け対象を提示する。個人環境の保存済みplanは使わない。
3. 承認されたplanの適用とコード配置を行い、まず手動実行でLambda・Glueを個別に確認する。
4. イベント連携で正常、Reject、スキーマ変更、障害、重複配送、途中失敗後の再実行を試す。実行履歴とS3の公開結果を照合する。開始権限拒否でpendingが残るケースは、[管理者復旧手順](aws-implementation.md#開始が確実に拒否された場合の管理者復旧)に沿ってCloudTrailの取得権限、未開始の証跡、所有者条件付き更新とロック解放を確認する。
5. 通知先への送信が許可されていることを確認し、システム障害時の通知と業務Reject時の無通知を確かめる。

完了条件は[構築完了の条件](#目的と完成条件)を実機で満たし、未検証事項と残っているリソース・費用を記録していること。

## AWS 5: Azureと比較して学ぶ

構築完了後に、Azure Phase 5〜7と合わせて行う。

1. AWS 1で固定した比較用データと、AWSの判定・出力を比較する。
2. サービス固有の違いと未検証事項を整理する。
3. Azure Phase 5・6で学んだ監視・冪等性と、AWSで先に決めた方式を比べる。
4. 学習終了後は、自分で作成した対象の削除planを確認して承認後に片付ける。共有リソースを削除対象に含めない。

完了条件は[学習の完成条件](#目的と完成条件)を満たし、費用と残すデータ・state・共有依存を説明できること。

## 後から追加する機能

次の機能は、AWS 4の構築完了後に機能追加として扱う。再開するときに、AzureとAWSのどちらから追加するか、Azure Phase 5〜7との順序を決め、AWS側のIssueを作る。

| 機能 | Azure | AWS側で追加する内容 |
|---|---|---|
| 外部データ取得 | [#28](https://github.com/Ries630/AzureDataTransformationLab/issues/28) | 取得用Step FunctionsからAthenaで提供元TableをSQL抽出し、イベント対象外へ保存した結果のうち、既存契約を満たす完成CSVだけを`landing`へ公開する。0件は正常終了して後段を起動しない |
| 対応表マスタ | [#29](https://github.com/Ries630/AzureDataTransformationLab/issues/29) | 対応表の保存先と、Glue ETLでのコード変換・参照版の扱い。保存先のサービスは追加時に選ぶ |

Athena取得を追加するときは、次を引き継ぐ。

- 取得から公開までと、公開後の検証・変換を別のワークフローに分け、取得側から後段を重ねて直接起動しない。取得の失敗と後段の失敗を切り分けるためである。
- [AthenaのSELECT結果CSV](https://docs.aws.amazon.com/athena/latest/ug/querying-finding-output-files.html)と[Athena連携](https://docs.aws.amazon.com/step-functions/latest/dg/connect-athena.html)の`.sync`を候補にする。
- 別アカウントTableの利用は、会社から提供された共有方式を使う。[Athenaのクロスアカウントアクセス](https://docs.aws.amazon.com/athena/latest/ug/lf-athena-limitations-cross-account.html)にはCatalog共有とLake Formationを使う方式があり、S3・KMSを含む権限も確認する。二つ目のアカウントを利用できなければ、自アカウントの学習用Catalogで確認し、クロスアカウント認可は未検証として記録する。
- 対象行と除外行を持つ固定サンプルと、通常の抽出と取得0件を再現するSQL・期待結果を用意する。
- AWS 0では、Athenaの権限とworkgroup、提供元サンプルTableの有無、別アカウントへの接続可否、Lake Formationの利用を追加で確認する。

## 判断と着手管理

AWS 1〜3は、Azure Phase 5〜7を待たずに、仮定とローカルで確認できる完了条件を具体化して着手する。未確認の会社権限はAWS 4の着手条件へ残す。AWS 1〜5は一段階ずつ着手する。着手順はGitHub Relationshipsを正とし、詳細計画が必要なIssueは`ready-for-agent`を付けず未割り当てで管理する。

構築を急ぐため、各段階の成果物はコード、Terraform、手順書、比較用データを優先する。学習用の解説（`docs/tutorials/`に相当するもの）はAWS 5で書く。

ADR候補は、入力世代と出力公開・冪等性の方式とする。Athena取得とGlue変換の役割分担、クロスアカウントを模擬する場合の制約は、[後から追加する機能](#後から追加する機能)の着手時に判定する。会社条件とAzureの検証結果を根拠に要否を判定し、必要な記録を承認済み実装に含める。root・stateの分離やZIP生成の一般的な手順は、手順書で扱う。

本番案件のデータ量・抽出条件・共有方式・起動条件・後段への受け渡しは、案件資料で確認してから別途反映する。
