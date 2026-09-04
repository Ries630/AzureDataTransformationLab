# Terraform planのPRレビュー

## 現在の実装範囲

[Issue #9](https://github.com/Ries630/AzureDataTransformationLab/issues/9)の表示・公開処理を準備している。現時点のGitHub Actionsは、架空のplanを使う検証だけを行う。Azure認証、実planの生成、PRへの自動投稿はまだ接続していない。

既存の7リソースのstateはlocal backendにある。空のstateをCIへ渡すと作成済みリソースも追加として表示されるため、stateの受け渡し方式を決めるまで実planのworkflowを有効にしない。

## ローカルで表示を確認する

Node.js 24を使用する。依存パッケージの追加は不要であり、GitHub ActionsのコメントAPIとの接続も同じJavaScriptで扱える。

```bash
LAB_RENDERER_DIR="$(mktemp -d)"
node scripts/terraform/install-tfplan2md.mjs "$LAB_RENDERER_DIR"
export TFPLAN2MD_PATH="$LAB_RENDERER_DIR/tfplan2md"

TFPLAN2MD_PATH="$TFPLAN2MD_PATH" node --test scripts/terraform/*.test.mjs
```

バージョンと公式配布物のSHA-256の正は[`tfplan2md.json`](../scripts/terraform/tfplan2md.json)とする。Linux x64とmacOS arm64を検証対象にする。インストーラーは取得したアーカイブのチェックサムが一致した場合だけ展開する。

既存の保存済みplanからレポートを作る場合は、[Phase 1の手順](learning-plan.md#phase-1-storage)で設定した`ARM_SUBSCRIPTION_ID`を使用する。

```bash
terraform -chdir=infra/terraform show -json phase1.tfplan \
  > infra/terraform/phase1.tfplan.json
node scripts/terraform/report.mjs \
  infra/terraform/phase1.tfplan.json \
  infra/terraform/phase1.tfplan.md
```

saved planを正とし、JSONとMarkdownは派生データとして扱う。作成済みの古いplanを現在の状態として再利用せず、実行日時と対象コミットを確認する。

## 公開境界

[`report.mjs`](../scripts/terraform/report.mjs)は元のplanでSubscriptionの一致、取得した名前、別Subscriptionへの参照、planの完了状態、操作種別を検証する。その後に表示専用コピーを作り、Terraformのsensitive情報で指定された値を除去し、UUIDを同じ入力に対して同じ架空UUIDへ置換する。

Providerの対象照合も同スクリプトで行う。[Terraformのplan JSON](https://developer.hashicorp.com/terraform/internals/json-format#expression-representation)にある`references`は式の依存先であり、評価結果ではない。変数を使うProviderでは、同じProviderに結び付いた`azurerm_client_config`の取得結果が必要になる。取得がapplyまで遅延するなど、対象を確定できないplanは公開しない。

`tfplan2md`はこのコピーだけを読み、GitHub向けに詳細を折りたたんだMarkdownを生成する。生成後も元の機密文字列とUUIDが残っていないか検査する。変換失敗、検証失敗、コメント上限超過の場合は出力を公開しない。診断に元データを転記しない。

この処理はSubscriptionの実在確認、Azureの認可、PRの信頼判定を代替しない。将来のworkflowでは、認証後の対象照合と保護された実行環境を別途必要とする。

[`comment.mjs`](../scripts/terraform/comment.mjs)は専用マーカーで始まる`github-actions[bot]`のコメントだけを更新する。人の同名コメント、fork、終了済みPR、古いPR headは対象にしない。実workflowでは同じPRの実行を直列化し、同時作成を防ぐ必要がある。

## CIと操作ユーザーの分離

CIのIdentityを使ってplanしても、既存のユーザー向けRole Assignmentの対象は変えない。CIでは`TF_VAR_operator_object_id`に操作ユーザーのObject IDを明示する。ローカルで省略した場合は従来どおり実行ユーザーを使う。変数の定義は[`variables.tf`](../infra/terraform/variables.tf)を参照する。

## state方式の決定後に接続する範囲

- stateの取得と、取得失敗時に空のstateへフォールバックしない処理
- 保護されたGitHub Environmentと、専用OIDC Identityの作成計画
- 対象限定の読み取り権限によるAzure認証と実planの生成
- 公開用Markdownだけを受け取るコメント投稿job
- PRの再実行、非信頼PR、実環境IDの非公開を含む実接続の検証

OIDCの構成では[GitHubのAzure向け手順](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-azure)に従い、Environmentの保護を組み合わせる。
