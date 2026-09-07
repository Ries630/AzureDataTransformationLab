# ADR-0005: PEP 723の依存関係をuvでAzure Functions用にパッケージする

- ステータス: 承認済み
- 検証状況: 固定Linux x86_64コンテナーで2回のクリーンビルド、ネイティブ依存のimport、manifestのlock SHA256と実配置依存の一致を確認済み。[PR #26のCI](https://github.com/Ries630/AzureDataTransformationLab/actions/runs/34083499804)でもUbuntu 24.04上のテストとLinuxパッケージ生成が成功。Azure上の検証は未実施
- 日付: 2026-09-07
- 関連: [Issue #16](https://github.com/Ries630/AzureDataTransformationLab/issues/16)

## 背景

このリポジトリでは、Pythonの依存関係をuvとPEP 723のインラインメタデータで管理する。`function_app.py`と隣接するロックファイルから、Functionのソースと依存関係の入力を一緒に確認できる。`requirements.txt`や`pyproject.toml`を別の正として置くと、同じ依存関係を二重に更新することになる。

Azure FunctionsのPythonアプリが実行時に使う依存関係は、発行パッケージ内の`.python_packages/lib/site-packages`へ配置する。PEP 723はuvが解決に使う入力であり、Azure Functionsのホストがそれを直接インストール手順として実行する形式ではない。そのため、ロックした依存関係をAzure Functionsの配置形式へ変換する工程をリポジトリで持つ。

MacとAzure FunctionsのLinux実行環境で依存パッケージの実行条件が異なるため、配置はLinux x86_64で行う。Macから実行する場合は、固定したLinux x86_64コンテナーを使う。

## 決定

次の方式で依存関係を管理し、Azure Functions用に配置する。

- `function_app.py`のPEP 723メタデータを入力とし、隣接するロックファイルで解決結果を固定する。
- ローカル実行とパッケージ生成では`--locked`を使い、実行時にロックを変更しない。
- `scripts/validator/package.py`でロックを一時的にrequirements形式へエクスポートし、ハッシュ検証とwheel限定で`.python_packages/lib/site-packages`へ配置する。requirements形式のファイルは生成処理の一時入力とし、Gitへコミットしない。
- 生成処理はFunctionコード、`host.json`、`.funcignore`、依存パッケージ、manifestを新規の発行ディレクトリへまとめる。生成物はGit管理外とする。
- 生成済みディレクトリを`--no-build`の発行元として使う。CIでも同じロックとLinux x86_64の生成処理を実行する。

具体的な生成、再生成、発行手順と完了条件は[学習計画のPhase 2](../learning-plan.md#phase-2-azure-functionsによる入力検証)を参照する。HTTP契約と検証規則は[アーキテクチャ](../architecture.md#azure-functionsの責務)を正とする。

## 検討した代替

`requirements.txt`を依存関係の正にする方式はAzure Functionsの標準的な配置形式に合うが、リポジトリのPEP 723・uv方針と別の入力ファイルを維持することになるため採用しない。

`pyproject.toml`を作成してuvプロジェクトとして管理する方式は、プロジェクト単位の依存関係には適している。一方、単一Functionスクリプトのインラインメタデータと管理境界が変わるため、今回のPhaseでは採用しない。

Mac上で直接`.python_packages`を生成する方式は、Linux上で使うwheelやネイティブ依存と一致しない可能性があるため採用しない。

## 受け入れた代償

Linux x86_64の生成環境とPythonヘルパーを維持する必要がある。`.python_packages`自体をレビュー対象にできないため、ロックファイル、生成処理、manifest、import確認をレビュー対象にする。依存関係が増えた場合は、生成物のサイズと起動時間を再確認する。

## 再評価の条件

- PEP 723またはuvのロック・エクスポート仕様が変わり、解決結果を固定できなくなった場合
- ネイティブ依存、パッケージサイズ、起動時間が現在の生成方式の制約を超えた場合
- Azure Functionsの配置方式またはリポジトリのPython依存管理方針を変更する場合
- CIまたはAzureの検証で、同じロックから生成したパッケージを再現できない場合

## 根拠

- [PEP 723: Inline script metadata](https://peps.python.org/pep-0723/)
- [uvでスクリプトを実行する](https://docs.astral.sh/uv/guides/scripts/)
- [uv CLI reference](https://docs.astral.sh/uv/reference/cli/)
- [Deploy your Python apps to Azure Functions](https://learn.microsoft.com/en-us/azure/azure-functions/python-build-options)
