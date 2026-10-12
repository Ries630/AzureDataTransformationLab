# AWS版の実装と会社学習環境への持ち込み計画

ステータス: Issue化済み。実装・実機操作は未着手。全体は[親Issue #30](https://github.com/Ries630/AzureDataTransformationLab/issues/30)、進捗は[AWS milestone](https://github.com/Ries630/AzureDataTransformationLab/milestone/2)で管理する。AWSコードの実装と会社環境への適用は、各段階の着手条件を確認して進める。

| 段階 | Issue |
|---|---|
| AWS 0: 環境確認 | [#31](https://github.com/Ries630/AzureDataTransformationLab/issues/31) |
| AWS 1: 共通契約・比較基準 | [#32](https://github.com/Ries630/AzureDataTransformationLab/issues/32) |
| AWS 2: コード・IaC | [#33](https://github.com/Ries630/AzureDataTransformationLab/issues/33) |
| AWS 3: 持ち込みZIP | [#34](https://github.com/Ries630/AzureDataTransformationLab/issues/34) |
| AWS 4: 会社での実演 | [#35](https://github.com/Ries630/AzureDataTransformationLab/issues/35) |

## 目的と完成条件

Azureで検証したデータ取得・検証・変換・監視・再実行をAWS向けに実装し、会社の学習環境で同じサンプルと期待結果を使って学ぶ。個人側ではソースと配置用成果物を作成し、AWS実機での確認は会社の学習環境で行う。

完成条件は次のとおりとする。

- 会社で許可された方法でコードと成果物を持ち込み、個人GitHubへのログインに依存せず配置できる。
- Athenaで学習用テーブルから抽出し、自分のS3領域へ保存して検証・変換につなげられる。
- 正常入力、業務Reject、取得0件、システム障害、スキーマ変更、再実行を実演できる。
- Azure版とAWS版の判定・出力を比較し、サービス固有の違いを説明できる。
- Terraformと配置手順から構築・更新・後片付けを再現できる。

会社でAWS学習環境が利用可能で、自分用のIAMアカウントが用意されている。IAMの紐づき先と実行権限は未確認。持ち込みはファイル転送とし、コードと配置物を一つのZIPにまとめる。Terraform・AWS CLIは利用可能と仮定して準備し、会社での初回接続時に実行可否を確認する。業務案件の本番仕様とは分けて扱う。

## Azureを終えるまでの順序

Azureの実装・検証の正は[学習計画](learning-plan.md)、外部SQL取得の正は[Issue #28](https://github.com/Ries630/AzureDataTransformationLab/issues/28)とする。

| 順序 | 対象 | AWS版へ引き継ぐ成果 |
|---|---|---|
| 1 | Phase 3 / #17 | 正常・Reject・障害の処理経路と実出力 |
| 2 | Phase 4 / #18 | 列追加・必須列削除・型変更の許容と拒否 |
| 3 | 対応表マスタ / #29 | DB参照・コード変換・参照版の比較結果。AWSへの移植範囲はAWS 1で棚卸しする |
| 4 | 外部SQL取得 / #28 | 抽出SQL、対象行・除外行のサンプル、0件と公開失敗の挙動 |
| 5 | Phase 5 / #19 | 取得側と後段側の監視、通知条件、費用の把握 |
| 6 | Phase 6 / #20 | 入力の世代識別、重複防止、Retry、途中失敗後の再実行 |
| 7 | Phase 7 / #21 | 再構築手順と一連の実演結果 |

2026-10-10の確認では、`origin/main`の最新tipは`119d29a`でPhase 2までが取り込まれている。Phase 3は[PR #27](https://github.com/Ries630/AzureDataTransformationLab/pull/27)がOPENで、作業ブランチに定義がある。Issue #17〜#21と#28はOPENであり、コードの存在を学習完了とは扱わない。

Phase 7で、入力、抽出結果、検証結果、最終出力を比較用データとして固定する。列と値、decimalの精度・丸め、日時のタイムゾーン、未知列、行数、重複時の出力を比較対象にし、CSVの行順やサービス固有の実行IDは一致条件に含めない。詳細な規則は[アーキテクチャ](architecture.md)を参照し、比較用データに複製しない。

## AWS 0: 会社環境の条件確認

会社環境の確認はAzure学習と並行できる。ファイル転送とTerraform・AWS CLIを使う構成でコードと配置物の準備を進め、環境値は会社で設定する。下表の未確認事項は、コード作成を一律に止める条件にはしない。配置物の形式を変える条件はbundle生成時、実行対象と権限は会社での初回接続・適用前に確定する。

| 確認事項 | 実装・持ち込みへの影響 |
|---|---|
| 利用アカウント、リージョン、利用期限、命名・タグの規則 | 対象の取り違え防止と削除範囲 |
| Terraform・AWS CLIの実行可否、Provider取得可否 | 個人側で生成するものと会社側で実行するもの。uvとビルド手段は個人側で使い、会社には配置済み成果物を渡す |
| IAMロール作成、PassRole、S3・Lambda・Step Functions・Glue・Athenaの権限 | 自分で作る範囲と管理者に用意してもらう範囲 |
| SSO／一時認証、permissions boundary、SCP、ネットワーク制限 | 実行主体、認可、SQLとStorageへのアクセス |
| Glue Catalog、Athena workgroup、KMSキー、S3、state保存先の提供状況 | 既存リソースの参照と新規作成の区別 |
| 提供元サンプルTableの有無、別アカウントへの接続可否、Lake Formationの利用 | 模擬用S3・Tableの作成範囲とクロスアカウント実演の範囲 |
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

着手条件はAzure Phase 7の完了と、この段階の実装計画の承認とする。Terraform・AWS CLIの利用とファイル転送を前提に進め、AWS 0の環境値と実行権限は配置前に確認する。

既存の`functions/validator/validation.py`の`validate_csv(content, filename)`とサンプル・純粋テストを再利用する。検証規則の正は[CSV検証規則](architecture.md#csv検証規則)に保ち、共通コードは一か所で管理してAzure用とLambda用の配置物に同梱する。共通コードの取り出しに伴うAzureのimport・パッケージ構築への変更を、この段階の検証範囲に含める。

Azure固有のHTTP入口、Managed Identity、Blob読み取り、配置用ディレクトリは、Lambda入口、実行ロール、S3読み取り、Lambda ZIPへ置き換える。Pythonの対象バージョンとCPUはAWSの対応環境から選び、bundleに記録する。会社固有の制約が判明した場合は配置物を再生成する。Azureの実行環境をそのまま引き継がない。

この段階で次を決める。

- SQL抽出結果から既存CSV契約への受け渡し。列名・金額・日時・引用符と改行を比較する。
- 入力S3のbucket・prefixと世代を限定し、検証後のコピーでも同じ世代を使う方法。
- `VALID`・`INVALID`とシステム障害の区別。業務Rejectは正常終了、取得・変換・保存の失敗は処理失敗とする。
- ワークフロー間で渡す入力参照、取得実行ID、オブジェクト世代、検証結果の参照。

完了条件は、Azureの比較用データに対する共通検証が変わらず、AWS固有の入出力・世代・失敗契約が明文化されていること。

## AWS 2: 取得と変換のコード・IaCを作る

### 構成案

```text
手動開始
  → 取得用Step Functions
      → Athenaで提供元TableをSQL抽出
      → S3 query-resultsへ保存
      → 結果の0件・形式・完成状態を確認
      → 完成CSVだけをS3 landingへ公開
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

入口の取得方式は[Issue #28](https://github.com/Ries630/AzureDataTransformationLab/issues/28)のAthena方針を引き継ぐ。Glue ETLは後段の変換を担当する。取得から公開までと、公開後の検証・変換を分けることで、Azureで学んだ処理経路と障害境界を比較できる。

Step Functionsは、AthenaとGlue Jobの完了を待つ処理に対応するStandardを候補とする。[Athena連携](https://docs.aws.amazon.com/step-functions/latest/dg/connect-athena.html)と[Glue連携](https://docs.aws.amazon.com/step-functions/latest/dg/connect-glue.html)の`.sync`を使い、開始APIの成功を処理完了と扱わない。Crawlerの開始後も完了確認とTimeoutを設ける。

### 実装する範囲

1. **S3と権限**: 提供元を参照する権限、自分の入出力領域、query-results・staging、実行ロールを定義する。提供元Tableが未提供なら、学習用の提供元S3領域、Glue Database・Tableの定義、架空サンプルの配置手順も作る。取得側の実行主体はその提供元を読み取り専用で参照する。提供済みのリソースは参照し、会社側の共有基盤は作成・変更対象から外す。
2. **SQL取得**: 学習用の固定SQLと期待結果から始める。[AthenaのSELECT結果CSV](https://docs.aws.amazon.com/athena/latest/ug/querying-finding-output-files.html)を候補とし、結果をイベント対象外へ保存したあと、既存契約を満たす完成CSVだけを公開する。0件は正常終了して後段を起動しない。
3. **Lambda検証**: 上限付きのS3読み取りと共通検証を接続する。検証結果の全文はS3へ保存し、Step Functionsには判定と参照を渡す。CSVや大量のエラーを状態データへ載せない。
4. **Crawler・ETL**: Crawlerは学習用の自分のデータだけを対象とし、外部の提供元Catalogを更新しない。Glueの実装方式・バージョンは会社の条件に合わせ、Azureで確定した変換結果と比較する。
5. **実行制御**: EventBridgeは`landing`の完成CSVに限定する。取得側から後段を重ねて直接起動せず、実行IDとS3参照で前後の履歴を対応付ける。重複配送、公開途中の失敗、Retry、再実行はAzure Phase 6の結果をAWSの機構へ対応付ける。
6. **監視・費用**: 取得・変換のシステム障害と業務Rejectを分ける。Athenaの処理量制限、Glueの同時実行・Timeout、ログ・一時データの保持期間を定める。費用は会社の予算で見積もる。

別アカウントTableの利用は、会社から提供された共有方式を使う。[Athenaのクロスアカウントアクセス](https://docs.aws.amazon.com/athena/latest/ug/lf-athena-limitations-cross-account.html)にはCatalog共有とLake Formationを使う方式があり、S3・KMSを含む権限も確認する。二つ目のアカウントを利用できなければ、自アカウントの学習用CatalogでSQL取得を確認し、クロスアカウント認可は未検証として記録する。模擬する場合は対象行と除外行を持つ固定サンプルを用意し、通常の抽出と取得0件をそれぞれ再現するSQL・期待結果を含める。

### Terraformと配置物

- AWS用rootは`infra/aws/`を候補とし、Azure用root・stateから分離する。
- 実行対象アカウント・リージョンを検査し、会社の認証方式とstate保存先を使う。
- Lambda・Glue・SQL・ワークフロー定義はGit管理し、配置用コードとインフラの更新手順を辿れるようにする。
- Python依存はPEP 723と隣接lockを正とし、Lambdaの対象環境に合わせてZIPを生成する。[Lambdaの配置仕様](https://docs.aws.amazon.com/lambda/latest/dg/python-package.html)に合わせ、Boto3を含む依存を固定して同梱する。
- Glue用コードの依存と配置方法はLambdaと分け、選択するGlueランタイムの条件を記録する。
- Providerはlockで固定する。会社で取得できない場合は、許可された配布方法で対象OS・CPU用のmirrorを用意する。

完了条件は、環境値を会社で設定できるコードとTerraformが揃い、認証不要のPR検査で共通検証・AWSアダプター・生成ZIP・IaCを確認できること。未確認の会社条件と仮定を記録し、実APIの権限とサービス連携はAWS 4で確認する。

## AWS 3: 持ち込み用bundleを作る

ファイル転送できる一つのZIPへまとめ、会社では展開して環境値を設定する。Lambda・Glueの配置物は個人側で生成し、会社でのソース再ビルドを通常手順に含めない。Providerは会社で取得する手順を基本とし、取得できない場合に対象OS・CPU用のmirrorを同梱する。

| 同梱物 | 内容 |
|---|---|
| ソースとlock | 共通検証、AWS固有コード、SQL、ワークフロー、Terraform、依存の固定情報 |
| 配置用成果物 | Lambda ZIP、Glueスクリプト、必要な依存、許可された場合のProvider mirror |
| 学習データと取得元 | 架空の提供元サンプル、模擬用S3・Catalog定義と配置手順、通常・0件の抽出SQL、検証・変換の期待結果 |
| 環境設定の例 | アカウント・リージョン・既存リソース・命名・タグ・stateを会社で設定する項目 |
| 操作手順 | 前提確認、init、plan、配置、実演、障害調査、後片付け、途中中断からの再開 |
| manifest | ソースcommit、対象ランタイム・CPU、依存版、各成果物のSHA-256、検証結果 |

bundleは許可したファイルから生成し、認証情報、個人の`.tfvars`、state、保存済みplan、ログ、実データを含めない。会社の環境値は会社側で設定する。

完了条件は、別の空ディレクトリへ展開したbundleだけで、manifest照合、配置物のimport、サンプル検証、`terraform init -backend=false`と`terraform validate`まで再現できること。オフライン利用が必要な場合はネットワークなしで確認する。会社のbackendへの接続と実planはAWS 4で行い、ローカルで確認した範囲と実機未確認の範囲をmanifestへ記録する。

## AWS 4: 会社へ持ち込み、実機で学ぶ

この段階は会社の許可された端末と認証で実施する。コードの実装承認とは別に、会社環境への適用、サンプル投入、通知の送信、削除の承認を確認する。

1. 持ち込み後にSHA-256と対象アカウント・リージョン・実行ロールを照合する。
2. 会社の環境値とstate保存先を設定してplanを作る。変更対象、権限、費用、配置するコード、後片付け対象を提示する。個人環境の保存済みplanは使わない。
3. 承認されたplanの適用とコード配置を行い、まず手動実行で取得・Lambda・Glueを個別に確認する。
4. イベント連携で正常、Reject、0件、スキーマ変更、障害、重複配送、途中失敗後の再実行を試す。前後の実行履歴とS3の公開結果を照合する。
5. 通知先への送信が許可されていることを確認し、システム障害時の通知と業務Reject時の無通知を実演する。
6. Azureの比較用データと判定・出力を比較する。サービス固有の違いと未検証事項を記録する。
7. 学習終了後は、自分で作成した対象の削除planを確認して承認後に片付ける。共有リソース・提供元データを削除対象に含めない。

完了条件は[目的と完成条件](#目的と完成条件)を実機で満たし、費用と残すデータ・state・共有依存を説明できること。

## 判断と着手管理

Azureの既存Issueを先に完了し、AWS 1〜3は仮定とローカルで確認できる完了条件を具体化して着手する。未確認の会社権限はAWS 4の着手条件へ残す。AWS 1〜4は一段階ずつ着手し、AWS 4は実環境での検証手順として扱う。着手順はGitHub Relationshipsを正とし、詳細計画が必要なIssueは`ready-for-agent`を付けず未割り当てで管理する。

ADR候補は、Athena取得とGlue変換の役割分担、入力世代と出力公開・冪等性の方式、クロスアカウントを模擬する場合の制約とする。会社条件とAzureの検証結果を根拠に要否を判定し、必要な記録を承認済み実装に含める。root・stateの分離やZIP生成の一般的な手順は、手順書で扱う。

本番案件のデータ量・抽出条件・共有方式・起動条件・後段への受け渡しは、案件資料で確認してから別途反映する。
