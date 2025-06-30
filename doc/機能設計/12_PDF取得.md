# 12. PDF取得 機能設計書

## 1. 機能概要

- 指定したplan_idに対して、設計書PDF（manual_pdf）を返却するAPI。
- 事前にPDF取得可否確認APIでready: trueの場合のみ利用可能。

## 2. 入出力仕様

### 入力

- HTTPメソッド: GET
- エンドポイント: `/api/{plan_id}/manual_pdf`
- パスパラメータ: `plan_id`（画像アップロード時に発行されたUUID）

### 出力

- 成功時: base64でエンコードされたPDFバイナリ（HTTP 200）
  - レスポンスヘッダー:
    - Content-Type: application/pdf
    - Content-Disposition: attachment; filename="design_document.pdf"
- 失敗時: `{ "error": "エラーメッセージ" }`（HTTP 400/404/500）
  - レスポンスヘッダー:
    - Content-Type: application/json

## 3. 処理フロー

1. plan_id（UUID形式）をバリデーション
   - UUID形式でない場合は400エラー
2. Google Cloud Storage（バケット名: `plan-craft-test-bucket` など）に設計書PDFファイル（`plan_id/manual.pdf` など）が存在するか確認
   - 存在しない場合は404エラー
3. PDFファイルをbase64エンコードし、レスポンスとして返却（HTTP 200）

## 4. バリデーション

- plan_idがUUID形式であること

## 5. エラーハンドリング

| エラーケース                | ステータスコード | レスポンス例                                 | 備考                         |
|----------------------------|------------------|---------------------------------------------|------------------------------|
| plan_idがUUID形式でない    | 400              | { "error": "plan_idがUUID形式ではありません" } | 形式不正                     |
| plan_idが存在しない・PDF未生成 | 404         | { "error": "指定plan_idが存在しない、またはPDF未生成" } | データ未登録                 |
| GCSアクセス失敗・内部エラー| 500              | { "error": "サーバ内部エラー" }             | 予期しない例外                |

## 6. 備考

- 事前にPDF取得可否確認API（/api/{plan_id}/manual_pdf/ready）でready: trueの場合のみ利用可能
- レスポンスのPDFはbase64エンコードで返却
- curl例: 
  ```sh
  curl -X GET http://localhost:8000/api/123e4567-e89b-12d3-a456-426614174000/manual_pdf --output manual.pdf
  ```
