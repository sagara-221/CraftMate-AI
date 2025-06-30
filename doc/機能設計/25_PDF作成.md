# 25. PDF作成 機能設計書

## 1. 機能概要

- 部品3Dモデル情報・部品作成手順・組立手順のJSONデータをもとに、DIY設計書（PDF）を自動生成する。
- 3Dモデル画像や部品画像、組立手順画像を自動生成し、Markdown→PDF変換を行う。
- 生成したPDFはGoogle Cloud Storage（GCS）に保存する。

## 2. 入力

- plan_id（UUID形式）
- GCS上の以下のJSONファイル
  - `{plan_id}/parts3d.json`（部品3Dモデル情報）
  - `{plan_id}/parts_manual.json`（部品作成手順）
  - `{plan_id}/assembly_manual.json`（組立手順）

## 3. 出力

- `{plan_id}/design_document.pdf`（GCS上に保存されるDIY設計書PDF）

## 4. 主な処理フロー

1. GCSから3つのJSONファイル（parts3d, parts_manual, assembly_manual）を取得
2. 3Dモデル画像・部品画像・組立手順画像を自動生成
3. Markdown形式で設計書本文を生成
4. Markdown→HTML→PDF変換を実施
5. 生成したPDFをGCSにアップロード
6. 一時ファイル・ディレクトリを削除

## 5. 外部連携

- Google Cloud Storage（GCS）
- plotly（3D画像生成）
- markdown, weasyprint（Markdown→PDF変換）

## 6. エラーハンドリング

- 入力JSONが存在しない・不正な場合は例外発生、エラーログ出力
- PDF生成・画像生成・GCSアップロード失敗時も例外発生、エラーログ出力
- 例外発生時は一時ファイルをクリーンアップ

## 7. 備考

- 一時ファイルはGCP環境では `/tmp/{plan_id}/` 配下のみを利用
- 画像生成・PDF変換はメモリ消費が大きいため、App Engineのインスタンスクラス(F2以上推奨※F1は動かなかった)に注意
- 生成PDFは `/api/<plan_id>/manual_pdf/ready` で取得可否確認、`/api/<plan_id>/manual_pdf` でダウンロード可能
