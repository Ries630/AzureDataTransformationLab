# AWS版の持ち込みZIP

会社へ持ち込むZIPは、生成済みLambda ZIP、Glue・ワークフロー・Terraform、ソースとlock、架空サンプル・期待結果、配置手順を一式で含む。会社では展開して環境値を設定し、ソースの再ビルドと個人GitHubへのログインを通常操作に含めない。段階と完成条件は[AWS計画](aws-learning-plan.md#aws-3-持ち込み用bundleを作る)、適用する処理は[AWS処理契約](aws-architecture.md)を参照する。

AWS 3は配置物の準備と展開後の検査を行う。ファイル転送、会社AWSへの適用、通知送信、サンプル投入、実データの削除はAWS 4以降で会社の許可を確認して行う。会社の実権限・サービス連携・費用は未確認。

## 同梱物と記録

ソースcommitのGit管理済みファイルから、明示した許可リストだけを収集する。元のリポジトリ相対配置を保つため、TerraformからGlue・ワークフローへの参照と文書のリンクをそのまま使える。

| 場所 | 内容 |
|---|---|
| `dist/aws/lambda.zip` | Linux arm64 / Python 3.14向けに生成・実importを確認するLambda配置物 |
| `functions/`、`glue/`、`workflows/aws/` | 共通検証とAWS入口、変換、状態機械のソースとlock |
| `infra/aws/pipeline/` | 独立Terraform root、Provider lock、会社設定とbackendの例 |
| `samples/` | 架空入力と固定期待結果 |
| `scripts/aws/` | 配置物生成・検査、PowerShellとWSLのhash確認 |
| `docs/` | 必要な処理契約、配置・運用手順と参照文書 |
| `manifest.json` | ソースcommit、対象ランタイム・CPU・依存版、同梱ファイルhashと検査記録 |
| `checksums.sha256` | 同梱ファイルのhash一覧。Pythonなしで照合できる形式 |
| `manifest.sha256` | manifestとhash一覧の照合用hash |

認証情報、個人の設定・tfvars、state、保存済みplan、ログ、実データ、Git情報、キャッシュを同梱しない。`manifest.json`と`manifest.sha256`は、自己参照を避けるためmanifest内のファイルhashの対象外とする。`checksums.sha256`はpayloadのhash一覧を保持し、manifestにも一覧ファイル自体のhashを記録する。`manifest.sha256`はmanifestと一覧ファイルのhashを保持する。

manifestとZIP内の`package-manifest.json`を照合し、共通検証コードと依存lockが対象ソースに一致する配置物を使う。ZIP内のhash記録だけでは配布元の真正性を確認できないため、受信時にはZIP全体のSHA-256を信頼できる別の経路で受け取って照合する。

## 生成側の手順

ソースと文書をcommitし、そのcommitに一致するLambda ZIPを[生成手順](aws-implementation.md#コードと配置物)で用意する。以下の`SOURCE_COMMIT`と各パスを実値へ置き換え、draft・最終ZIPとreportには存在しない新規ファイルを指定する。既定のソースリポジトリは生成スクリプトが置かれたリポジトリで、別の取得先を使う場合は`--repo`で指定する。

```bash
uv run scripts/aws/bundle.py /tmp/aws-bundle-draft.zip --lambda-zip /tmp/adtl-lambda.zip --commit SOURCE_COMMIT
mkdir /tmp/aws-bundle-extracted
unzip -q /tmp/aws-bundle-draft.zip -d /tmp/aws-bundle-extracted
uv run scripts/aws/check_bundle.py /tmp/aws-bundle-extracted --report /tmp/aws-bundle-report.json
uv run scripts/aws/bundle.py /tmp/aws-transfer-bundle.zip --lambda-zip /tmp/adtl-lambda.zip --commit SOURCE_COMMIT --report /tmp/aws-bundle-report.json
```

展開後の検査にはLinux arm64 / Python 3.14、Terraform、bash、`sha256sum`、PowerShellの`pwsh`が必要。これは生成側の検査環境であり、会社PCでPythonを使う要件ではない。reportは展開ディレクトリの外へ置く。最終生成では同じcommitとLambda ZIPを使い、ソース・payloadのhash、対象環境と成功した検査項目が一致するreportだけを受け付ける。reportなしのdraftはmanifestの`verification.status=not_checked`、検査を反映した最終ZIPは`passed`になる。どちらも会社への配置検証を意味する`deploymentVerified`は`false`のまま。

配布物のPR検査（`.github/workflows/aws-bundle.yml`）は、このdraft生成、空ディレクトリへの展開、独立検査、同じpayloadからの最終生成をLinux arm64で行う。成功した実行の`aws-transfer-bundle` artifactに、最終ZIP、ZIP全体のSHA-256ファイル、検査reportを保存する。受け取るファイルは対象commitと成功した検査実行を照合して選ぶ。ダウンロードしたZIPの具体的なSHA-256は、配布する実体ごとに確認する。

## 受信時の照合

会社で許可された方法でZIPと、そのZIPのSHA-256を受け取る。以下のパスは実際の受信ファイルに置き換える。

PowerShell 5.1以上:

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath .\aws-bundle.zip
```

WSL:

```bash
sha256sum aws-bundle.zip
```

表示値が別途受け取ったSHA-256と一致した後、新しい空ディレクトリへ展開する。PowerShellでは次を使える。

```powershell
Expand-Archive -LiteralPath .\aws-bundle.zip -DestinationPath .\aws-bundle
```

WSLでは`unzip aws-bundle.zip -d aws-bundle`で展開する。既存の展開先へ重ねて展開せず、bundleのルートへ移動して同梱のhash確認スクリプトを実行する。**展開直後、会社のtfvars・backend設定・`.terraform`・実行結果などを追加する前に確認する。**未掲載ファイルも拒否するため、会社設定後のディレクトリを元の配布物として再検査しない。Pythonは不要。

PowerShell:

```powershell
.\scripts\aws\verify-bundle.ps1
```

WSL:

```bash
bash scripts/aws/verify-bundle.sh
```

欠落や改変が検出された場合は配置を止め、ZIPを再取得して独立したSHA-256から照合し直す。確認スクリプトの実行は会社のPowerShell実行ポリシーに従い、ポリシーを無断で変更しない。

## 会社の環境値と配置

確認後は[`infra/aws/pipeline/README.md`](../infra/aws/pipeline/README.md#設定)に沿って、会社の認証、対象アカウント・リージョン、自分用の命名とprefix、state保存先、通知先と保持期間を設定する。`lambda_zip_path`には同梱の`dist/aws/lambda.zip`をrootから参照する相対パスを指定する。提供済みbucketでは専用prefixとEventBridgeの有効化確認が必要。

TerraformとAWS CLIは会社で利用を許可されたものを使い、認証とツールの実行環境をPowerShellまたはWSLのどちらかに揃える。会社で生成したplanを確認し、承認後に適用する。個人側の保存済みplanを転用しない。受け入れ確認、再実行、ロック復旧は[配置・運用手順](aws-implementation.md)を参照する。

Providerは通常、会社での`terraform init`時にネットワークから取得する。今回のZIPにProvider mirrorは含めない。会社で取得できない場合は、使うOS・CPUと配布方法、オフライン要件を確認して対象mirrorを追加生成し、その構成をネットワークなしで検査してから使用する。WindowsとWSLが利用可能でも、CPUと取得可否が確認できたとは扱わない。

## 検査の境界

生成側では新しい空ディレクトリへ展開し、元checkout・個人設定・既存キャッシュに頼らず、同梱内容のhash、Linux arm64でのLambda実import、固定サンプルの検証期待値、`terraform init -backend=false`と`terraform validate`を確認する。manifestの検査記録は、検査したファイルのhashに対応する。

これらは認証不要の配置準備の検査であり、会社のIAM、EventBridge・Crawler・Glueの実連携、実通知、実backend・plan、費用を検証したものではない。会社での確認は[AWS 4](aws-learning-plan.md#aws-4-会社へ持ち込み構築を完了する)で行う。
