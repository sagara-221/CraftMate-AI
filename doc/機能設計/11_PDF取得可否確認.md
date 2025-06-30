# 11. PDF取得可否確認 機能設計書

## 1. 機能概要

- 指定したplan_idに対して、設計書PDFが取得可能かどうかを判定し返却するAPI。
- クライアントはこのAPIでready: trueの場合のみ、PDF取得APIを呼び出す。

## 2. 入出力仕様

### 入力

- HTTPメソッド: GET
- エンドポイント: `/api/{plan_id}/manual_pdf/ready`
- パスパラメータ: `plan_id`（画像アップロード時に発行されたUUID）

### 出力

- 成功時: `{ "ready": true }` または `{ "ready": false }`（HTTP 200）
- 失敗時: `{ "error": "エラーメッセージ" }`（HTTP 400/404/500）

## 3. 処理フロー

1. plan_id（UUID形式）をバリデーション
   - plan_idがUUID形式でない場合は400エラー
2. Google Cloud Storage（バケット名: `plan-craft-test-bucket` ）に設計書PDFファイル（`plan_id/manual.pdf` など）が存在するか確認
3. 存在すれば `{"ready": true}`、存在しなければ `{"ready": false}` を返却

## 4. バリデーション

- plan_idがUUID形式であること

## 5. エラーハンドリング

| エラーケース                | ステータスコード | レスポンス例                                 | 備考                         |
|----------------------------|------------------|---------------------------------------------|------------------------------|
| plan_idがUUID形式でない    | 400              | { "error": "plan_idがUUID形式ではありません" } | 形式不正                     |
| plan_idが存在しない        | 404              | { "error": "指定plan_idが存在しません" }      | データ未登録                 |
| GCSアクセス失敗・内部エラー| 500              | { "error": "サーバ内部エラー" }             | 予期しない例外                |

## 6. 備考

- ready: trueの場合のみPDF取得API（/api/{plan_id}/manual_pdf）を呼び出すこと
- レスポンスのContent-Typeはapplication/json
- curl例: 
  ```sh
  curl -X GET http://localhost:8000/api/123e4567-e89b-12d3-a456-426614174000/manual_pdf/ready
  ```
