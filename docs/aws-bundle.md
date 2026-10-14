# AWS版の持ち込みZIP

会社へ持ち込むZIPは、生成済みLambda ZIP、Glue・ワークフロー・Terraform、ソースとlock、架空サンプル・期待結果、配置手順を一式で含む。会社では展開して環境値を設定し、ソースの再ビルドと個人GitHubへのログインを通常操作に含めない。段階と完成条件は[AWS計画](aws-learning-plan.md#aws-3-持ち込み用bundleを作る)、適用する処理は[AWS処理契約](aws-architecture.md)を参照する。

AWS 3は配置物の準備と展開後の検査を行う。ファイル転送、会社AWSへの適用、通知送信、サンプル投入、実データの削除はAWS 4以降で会社の許可を確認して行う。会社の実権限・サービス連携・費用は未確認。

## 同梱物と記録

ソースcommitのGit管理済みファイルから、明示した許可リストだけを収集する。元のリポジトリ相対配置を保つため、TerraformからGlue・ワークフローへの参照と文書のリンクをそのまま使える。

| 場所 | 内容 |
|---|---|
| `dist/aws/lambda.zip` | 指定したLinux arm64またはx86_64 / Python 3.14向けに生成・実importを確認するLambda配置物 |
| `functions/`、`glue/`、`workflows/aws/` | 共通検証とAWS入口、変換、状態機械のソースとlock |
| `infra/aws/pipeline/` | 独立Terraform root、Provider lock、会社設定とbackendの例 |
| `samples/` | 架空入力と固定期待結果 |
| `scripts/aws/` | 配置物生成・検査、PowerShellとWSLのhash確認 |
| `docs/` | 必要な処理契約、配置・運用手順と参照文書 |
| `manifest.json` | ソースcommit、対象ランタイム・CPU・依存版、同梱ファイルhashと検査記録 |
| `checksums.sha256` | 同梱ファイルのhash一覧。Pythonなしで照合できる形式 |
| `manifest.sha256` | manifestとhash一覧の照合用hash |

認証情報、個人の設定・tfvars、state、保存済みplan、ログ、実データ、Git情報、キャッシュを同梱しない。`manifest.json`と`manifest.sha256`は、自己参照を避けるためmanifest内のファイルhashの対象外とする。`checksums.sha256`はpayloadのhash一覧を保持し、manifestにも一覧ファイル自体のhashを記録する。`manifest.sha256`はmanifestと一覧ファイルのhashを保持する。

manifestとZIP内の`package-manifest.json`を照合し、共通検証コードと依存lockが対象ソースに一致する配置物を使う。ZIP内のhash記録だけでは配布元の真正性を確認できない。会社での受信時の照合は任意とし、行う条件は[受信と展開](#受信と展開)に置く。

## 生成側の手順

ソースと文書をcommitし、そのcommitに一致するLambda ZIPを[生成手順](aws-implementation.md#コードと配置物)で用意する。Lambdaの既定CPUはarm64。x86_64のLambdaを選ぶ場合は、Linux x86_64の生成環境で次を実行する。

```bash
uv run scripts/aws/package.py /tmp/adtl-lambda.zip --architecture x86_64 --python-version 3.14
```

arm64を選ぶ場合は、Linux arm64の生成環境で`--architecture arm64`を指定する。以下の`SOURCE_COMMIT`と各パスを実値へ置き換え、draft・最終ZIPとreportには存在しない新規ファイルを指定する。既定のソースリポジトリは生成スクリプトが置かれたリポジトリで、別の取得先を使う場合は`--repo`で指定する。

```bash
uv run scripts/aws/bundle.py /tmp/aws-bundle-draft.zip --lambda-zip /tmp/adtl-lambda.zip --commit SOURCE_COMMIT
mkdir /tmp/aws-bundle-extracted
unzip -q /tmp/aws-bundle-draft.zip -d /tmp/aws-bundle-extracted
uv run scripts/aws/check_bundle.py /tmp/aws-bundle-extracted --report /tmp/aws-bundle-report.json
uv run scripts/aws/bundle.py /tmp/aws-transfer-bundle.zip --lambda-zip /tmp/adtl-lambda.zip --commit SOURCE_COMMIT --report /tmp/aws-bundle-report.json
```

展開後の検査には、manifestのLambda CPUに一致するLinux arm64またはx86_64 / Python 3.14、Terraform、bash、`sha256sum`、PowerShellの`pwsh`が必要。これは生成側の検査環境であり、会社PCでPythonを使う要件ではない。reportは展開ディレクトリの外へ置く。最終生成では同じcommitとLambda ZIPを使い、ソース・payloadのhash、対象環境と成功した検査項目が一致するreportだけを受け付ける。reportなしのdraftはmanifestの`verification.status=not_checked`、検査を反映した最終ZIPは`passed`になる。どちらも会社への配置検証を意味する`deploymentVerified`は`false`のまま。

配布物のPR検査（`.github/workflows/aws-bundle.yml`）は、このdraft生成、空ディレクトリへの展開、独立検査、同じpayloadからの最終生成をLinux arm64とLinux x86_64の各CPU上で行う。成功した実行の`aws-transfer-bundle-arm64`または`aws-transfer-bundle-x86_64` artifactに、最終ZIP、ZIP全体のSHA-256ファイル、検査reportを保存する。受け取るファイルは対象commitと成功した検査実行を照合して選ぶ。受信側で[任意の照合](#任意の照合)を行うときは、このSHA-256の値をZIPとは別の経路で参照する。

## 受信と展開

会社で許可された方法でZIPを受け取り、新しい空ディレクトリへ展開する。既存の展開先へ重ねて展開しない。以下のパスは実際の受信ファイルに置き換える。

PowerShell:

```powershell
Expand-Archive -LiteralPath .\aws-bundle.zip -DestinationPath .\aws-bundle
```

WSL:

```bash
unzip aws-bundle.zip -d aws-bundle
```

受信時のhash照合は必須にしない。ZIPは成功したCI実行のartifactから取得し、会社では許可された経路で転送する。配置する変更は会社で作るplanで確認する。照合を省くと、転送中の改変や、manifestと異なる同梱ファイルを検出できなくなる。学習環境ではこの手間を省くことを選ぶ。

### 任意の照合

転送経路に不安がある場合、展開で警告が出た場合、planに想定外の差分が出た場合は、次の照合を行う。

ZIPのSHA-256は、ZIPとは別の信頼できる経路で得た値と比べる。たとえば、転送前に生成側で`aws-transfer-bundle.zip.sha256`の値を控え、ZIPとは別の経路で参照する。ZIPと同じ経路で運んだ`.sha256`ファイルは、両方を置き換えられると一致してしまうため、改変がないことの根拠にならない。

PowerShell 5.1以上:

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath .\aws-bundle.zip
```

WSL:

```bash
sha256sum aws-bundle.zip
```

同梱ファイルの確認スクリプトは、**受け取ったZIPを新しい空ディレクトリへ展開し直し、そのルートで実行する。**スクリプトは一覧外のファイルも拒否するため、会社のtfvars・backend設定・`.terraform`・実行結果などを追加したディレクトリでは、改変がなくても失敗する。Pythonは不要。

PowerShell:

```powershell
.\scripts\aws\verify-bundle.ps1
```

WSL:

```bash
bash scripts/aws/verify-bundle.sh
```

欠落や改変が検出された場合は配置を止め、ZIPを再取得して照合し直す。確認スクリプトの実行は会社のPowerShell実行ポリシーに従い、ポリシーを無断で変更しない。

## 会社の環境値と配置

会社PCはWindowsとWSLが利用可能なx86_64。**会社PCのCPUと、AWS上で動くLambdaのCPUは別に選べる。**x86_64のPCからarm64のLambdaをTerraform・AWS CLIで配置・管理でき、会社PCでLambda ZIPを実行する必要はない。Lambdaの既定値はarm64のままとし、x86_64のLambdaを選ぶ場合はx86_64のartifactと一致する設定を使う。

確認後は[`infra/aws/pipeline/README.md`](../infra/aws/pipeline/README.md#設定)に沿って、会社の認証、対象アカウント・リージョン、自分用の命名とprefix、state保存先、通知先と保持期間を設定する。`lambda_zip_path`には同梱の`dist/aws/lambda.zip`をrootから参照する相対パスを指定する。提供済みbucketでは専用prefixとEventBridgeの有効化確認が必要。manifestの`runtimes.lambda.architecture`とTerraformの`lambda_architecture`を一致させる。x86_64のLambda ZIPを使う場合は`company.tfvars`に`lambda_architecture = "x86_64"`を指定する。

TerraformとAWS CLIは会社で利用を許可されたものを使い、認証とツールの実行環境をPowerShellまたはWSLのどちらかに揃える。会社で生成したplanを確認し、承認後に適用する。個人側の保存済みplanを転用しない。受け入れ確認、再実行、ロック復旧は[配置・運用手順](aws-implementation.md)を参照する。

Providerは通常、会社での`terraform init`時にネットワークから取得する。今回のZIPにProvider mirrorは含めない。会社で取得できない場合は、使うOS・CPUと配布方法、オフライン要件を確認して対象mirrorを追加生成し、その構成をネットワークなしで検査してから使用する。会社PCのCPUはx86_64と確認済みだが、Providerの取得権限・ネットワークとオフライン要件は未確認。取得が妨げられる場合だけ、Windows用は`windows_amd64`、WSL用は`linux_amd64`から使う環境を選んでmirrorを追加する。

## 検査の境界

生成側では新しい空ディレクトリへ展開し、元checkout・個人設定・既存キャッシュに頼らず、同梱内容のhash、manifestに一致するLinux CPUでのLambda実import、固定サンプルの検証期待値、`terraform init -backend=false`と`terraform validate`を確認する。manifestの検査記録は、検査したファイルのhashに対応する。

これらは認証不要の配置準備の検査であり、会社のIAM、EventBridge・Crawler・Glueの実連携、実通知、実backend・plan、費用を検証したものではない。会社での確認は[AWS 4](aws-learning-plan.md#aws-4-会社へ持ち込み構築を完了する)で行う。
