from flask import (
    Flask,
    request,
    jsonify,
    Response,
    send_file,
    send_from_directory,
    make_response,
)
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import uuid
from google.cloud import storage
from ai_modules.parts_detection import detect_parts_from_bytes
from ai_modules.parts_loc_estimate import detect_parts_location_from_bytes
from ai_modules.parts_making import generate_parts_making
from ai_modules.create_assembly_steps import generate_assembly_manual
import threading
import io
import json
import logging
import base64
import os
from utils import (
    get_gcs_client_and_bucket,
    gcs_blob_exists,
    load_json_from_gcs,
    error_response,
    require_valid_uuid,
    parts3d_to_obj,
    allowed_file,
    upload_to_gcs,
    GCS_BUCKET_NAME,
    require_bearer_token,
)
from create_manual_pdf import make_manual_pdf
import google.cloud.logging
from google.cloud.logging.handlers import CloudLoggingHandler

app = Flask(__name__, static_folder="web", static_url_path="")
CORS(app)  # すべてのルートにCORSヘッダーを付与

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["20 per minute"],  # 例: 1分間に20回まで
)


MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10MB
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

# Cloud Loggingのセットアップ
client = google.cloud.logging.Client()
handler = CloudLoggingHandler(client)
logging.getLogger().addHandler(handler)
logging.getLogger().setLevel(logging.INFO)
app.logger.addHandler(handler)
app.logger.setLevel(logging.INFO)


@app.route("/", methods=["GET"])
def root():
    # web/index.htmlを返す
    return send_from_directory(app.static_folder, "index.html")


@app.route("/manifest.json")
def manifest():
    response = make_response(send_from_directory(app.static_folder, "manifest.json"))
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


# 21_部品検出
def detect_and_save_parts_list(image_bytes, mime_type, plan_id, bucket_name):
    try:
        logging.info(f"[parts_list] Detection start for plan_id={plan_id}")
        parts_list = detect_parts_from_bytes(image_bytes, mime_type)
        # GCSに保存
        _, bucket = get_gcs_client_and_bucket(bucket_name)
        blob = bucket.blob(f"{plan_id}/parts_list.json")
        blob.upload_from_string(
            data=json.dumps(parts_list, ensure_ascii=False, indent=2),
            content_type="application/json",
        )
        logging.info(
            f"[parts_list] Uploaded to gs://{bucket_name}/{plan_id}/parts_list.json"
        )
    except Exception as e:
        logging.error(f"[parts_list detection error] {e}")


# 22_部品3Dモデル作成
def estimate_and_save_parts3d(image_bytes, mime_type, parts_list, plan_id, bucket_name):
    try:
        logging.info(f"[parts3d] Estimation start for plan_id={plan_id}")
        parts3d = detect_parts_location_from_bytes(image_bytes, mime_type, parts_list)
        # GCSに保存（3D情報）
        _, bucket = get_gcs_client_and_bucket(bucket_name)
        blob = bucket.blob(f"{plan_id}/parts3d.json")
        blob.upload_from_string(
            data=json.dumps(parts3d, ensure_ascii=False, indent=2),
            content_type="application/json",
        )
        logging.info(f"[parts3d] Uploaded to gs://{bucket_name}/{plan_id}/parts3d.json")
        create_and_save_assembly_manual(
            parts3d, image_bytes, mime_type, plan_id, bucket_name
        )
    except Exception as e:
        logging.error(f"[parts3d estimation error] {e}")


# 23_部品作成手順生成
def create_and_save_parts_manual(parts_list, parts3d, plan_id, bucket_name):
    """parts3dから部品作成手順を生成し、Cloud Storageに保存する"""
    try:
        logging.info(f"[parts_manual] Generating for plan_id={plan_id}")
        parts_manual = generate_parts_making(parts_list, parts3d)
        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(f"{plan_id}/parts_manual.json")
        blob.upload_from_string(
            data=json.dumps(parts_manual, ensure_ascii=False, indent=2),
            content_type="application/json",
        )
        logging.info(
            f"[parts_manual] Uploaded to gs://{bucket_name}/{plan_id}/parts_manual.json"
        )
    except Exception as e:
        logging.error(f"[parts_manual error] {e}")


# 24_組立手順生成
def create_and_save_assembly_manual(
    parts3d, image_bytes, mime_type, plan_id, bucket_name
):
    """
    parts3d, 画像データ, mime_typeから組立手順を生成し、Cloud Storageに保存する
    """

    try:
        logging.info(f"[assembly_manual] Generating for plan_id={plan_id}")
        assembly_manual = generate_assembly_manual(image_bytes, mime_type, parts3d)
        _, bucket = get_gcs_client_and_bucket(bucket_name)
        blob = bucket.blob(f"{plan_id}/assembly_manual.json")
        blob.upload_from_string(
            data=json.dumps(assembly_manual, ensure_ascii=False, indent=2),
            content_type="application/json",
        )
        logging.info(
            f"[assembly_manual] Uploaded to gs://{bucket_name}/{plan_id}/assembly_manual.json"
        )
        return assembly_manual
    except Exception as e:
        logging.error(f"[assembly_manual error] {e}")
        return None


def try_create_manual_pdf(plan_id):
    """
    parts_manual.jsonとassembly_manual.jsonが両方存在する場合のみPDF生成
    """
    _, bucket = get_gcs_client_and_bucket()
    parts_manual_exists = gcs_blob_exists(bucket, f"{plan_id}/parts_manual.json")
    if not parts_manual_exists:
        logging.info(f"[manual_pdf] parts_manual.json not found for {plan_id}")
        return None
    assembly_manual_exists = gcs_blob_exists(bucket, f"{plan_id}/assembly_manual.json")
    if not assembly_manual_exists:
        logging.info(f"[manual_pdf] assembly_manual.json not found for {plan_id}")
        return None
    try:
        make_manual_pdf(plan_id, GCS_BUCKET_NAME)
        logging.info(f"[manual_pdf] PDF生成処理を実行しました: {plan_id}")
    except Exception as e:
        logging.error(f"[manual_pdf] PDF生成処理でエラー: {e}")


# 01_画像アップロード
@app.route("/api/upload", methods=["POST"])
@require_bearer_token
@limiter.limit("20 per day")
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "ファイルが添付されていません"}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "ファイルが選択されていません"}), 400
    if not allowed_file(file.filename):
        return jsonify({"error": "サポートされていないファイル形式です"}), 400
    filename = file.filename
    if "." not in filename:
        return jsonify({"error": "ファイル名に拡張子がありません"}), 400
    plan_id = str(uuid.uuid4())
    ext = filename.rsplit(".", 1)[1].lower()
    gcs_filename = f"{plan_id}/image.{ext}"
    try:
        # ファイルをGCSに保存
        file_bytes = file.read()
        file_stream = io.BytesIO(file_bytes)
        upload_to_gcs(file_stream, gcs_filename, file.content_type)
        logging.info(f"[upload] Image uploaded: {gcs_filename}")
        # 部品検出（2D）はバックグラウンドで実行
        threading.Thread(
            target=detect_and_save_parts_list,
            args=(file_bytes, file.content_type, plan_id, GCS_BUCKET_NAME),
            daemon=True,
        ).start()
        logging.info(
            f"[upload] Started parts_list detection thread for plan_id={plan_id}"
        )
    except Exception as e:
        logging.error(f"[upload error] {e}")
        return jsonify({"error": "GCS保存中にエラーが発生しました"}), 500
    return jsonify({"plan_id": plan_id}), 200


# 02_部品一覧取得可否確認
@app.route("/api/<plan_id>/parts/ready", methods=["GET"])
@require_bearer_token
@require_valid_uuid
def parts_ready(plan_id):
    _, bucket = get_gcs_client_and_bucket()
    ready = gcs_blob_exists(bucket, f"{plan_id}/parts_list.json")
    logging.info(f"[parts_ready] Checking parts_list for {plan_id}: {ready}")
    return jsonify({"ready": ready}), 200


# 03_部品一覧取得
@app.route("/api/<plan_id>/parts", methods=["GET"])
@require_bearer_token
@require_valid_uuid
@limiter.limit("15 per day")
def get_parts_list(plan_id):
    _, bucket = get_gcs_client_and_bucket()
    parts_list = load_json_from_gcs(bucket, f"{plan_id}/parts_list.json")
    if parts_list is None:
        logging.warning(f"[get_parts_list] parts_list.json not found for {plan_id}")
        return error_response("部品リストがまだ生成されていません", 404)
    # 画像ファイルもGCSから取得
    image_blob = None
    ext_found = None
    for ext in ["jpg", "jpeg", "png"]:
        img_blob = bucket.blob(f"{plan_id}/image.{ext}")
        if img_blob.exists():
            image_blob = img_blob
            ext_found = ext
            break
    if image_blob is None:
        logging.warning(f"[get_parts_list] image file not found for {plan_id}")
        return error_response("画像ファイルが見つかりません", 404)
    image_bytes = image_blob.download_as_bytes()
    mime_type = f"image/{ext_found}"
    threading.Thread(
        target=estimate_and_save_parts3d,
        args=(image_bytes, mime_type, parts_list, plan_id, GCS_BUCKET_NAME),
        daemon=True,
    ).start()
    logging.info(
        f"[get_parts_list] Started parts3d estimation thread for plan_id={plan_id}"
    )
    parts_list_simple = [
        {"part_id": i + 1, "part_name": parts["name"], "size": parts["size"]}
        for i, parts in enumerate(parts_list)
    ]
    return jsonify(parts_list_simple), 200


# 04_3D部品位置推定可否確認
@app.route("/api/<plan_id>/model/ready", methods=["GET"])
@require_bearer_token
@require_valid_uuid
def model_ready(plan_id):
    _, bucket = get_gcs_client_and_bucket()
    ready = gcs_blob_exists(bucket, f"{plan_id}/parts3d.json")
    logging.info(f"[model_ready] Checking parts3d for {plan_id}: {ready}")
    return jsonify({"ready": ready}), 200


# 05_3Dモデル情報取得
@app.route("/api/<plan_id>/model", methods=["GET"])
@require_bearer_token
@require_valid_uuid
@limiter.limit("20 per day")
def get_model_obj(plan_id):
    _, bucket = get_gcs_client_and_bucket()
    parts_list = load_json_from_gcs(bucket, f"{plan_id}/parts_list.json")
    if parts_list is None:
        logging.warning(f"[get_model_obj] parts_list.json not found for {plan_id}")
        return error_response("部品リストがまだ生成されていません", 404)
    parts3d = load_json_from_gcs(bucket, f"{plan_id}/parts3d.json")
    if parts3d is None:
        logging.warning(f"[get_model_obj] parts3d.json not found for {plan_id}")
        return error_response("3D部品位置がまだ生成されていません", 404)
    obj_text = parts3d_to_obj(parts3d)
    # 画像ファイルもGCSから取得
    image_blob = None
    ext_found = None
    for ext in ["jpg", "jpeg", "png"]:
        img_blob = bucket.blob(f"{plan_id}/image.{ext}")
        if img_blob.exists():
            image_blob = img_blob
            ext_found = ext
            break
    if image_blob is None:
        logging.warning(f"[get_model_obj] image file not found for {plan_id}")
        return error_response("画像ファイルが見つかりません", 404)
    image_bytes = image_blob.download_as_bytes()
    mime_type = f"image/{ext_found}"
    threading.Thread(
        target=create_and_save_parts_manual,
        args=(parts_list, parts3d, plan_id, GCS_BUCKET_NAME),
        daemon=True,
    ).start()
    threading.Thread(
        target=create_and_save_assembly_manual,
        args=(parts3d, image_bytes, mime_type, plan_id, GCS_BUCKET_NAME),
        daemon=True,
    ).start()
    headers = {
        "Content-Type": "text/plain; charset=utf-8",
        "Content-Disposition": 'inline; filename="model.obj"',
    }
    return Response(obj_text, status=200, headers=headers)


# 06_部品作成手順取得可否確認API
@app.route("/api/<plan_id>/parts_creation/ready", methods=["GET"])
@require_bearer_token
@require_valid_uuid
def parts_creation_ready(plan_id):
    _, bucket = get_gcs_client_and_bucket()
    ready = gcs_blob_exists(bucket, f"{plan_id}/parts_manual.json")
    logging.info(f"[parts_creation_ready] Checking parts_manual for {plan_id}: {ready}")
    return jsonify({"ready": ready}), 200


# 07_部品作成手順一覧取得API
@app.route("/api/<plan_id>/parts_creation", methods=["GET"])
@require_bearer_token
@require_valid_uuid
@limiter.limit("20 per day")
def get_parts_creation(plan_id):
    _, bucket = get_gcs_client_and_bucket()
    parts_manual = load_json_from_gcs(bucket, f"{plan_id}/parts_manual.json")
    if parts_manual is None:
        logging.warning(
            f"[get_parts_creation] parts_manual.json not found for {plan_id}"
        )
        return error_response("部品作成手順がまだ生成されていません", 404)
    threading.Thread(target=try_create_manual_pdf, args=(plan_id,), daemon=True).start()
    return jsonify(parts_manual), 200


# 08_組立手順取得可否確認
@app.route("/api/<plan_id>/assembly_parts/ready", methods=["GET"])
@require_bearer_token
@require_valid_uuid
def assembly_parts_ready(plan_id):
    _, bucket = get_gcs_client_and_bucket()
    ready = gcs_blob_exists(bucket, f"{plan_id}/assembly_manual.json")
    logging.info(
        f"[assembly_manual_ready] Checking assembly_manual for {plan_id}: {ready}"
    )
    return jsonify({"ready": ready}), 200


# 09_組立手順数取得
@app.route("/api/<plan_id>/assembly_parts/procedure_num", methods=["GET"])
@require_bearer_token
@require_valid_uuid
def get_assembly_procedure_num(plan_id):
    _, bucket = get_gcs_client_and_bucket()
    assembly_manual = load_json_from_gcs(bucket, f"{plan_id}/assembly_manual.json")
    if assembly_manual is None:
        logging.warning(
            f"[get_assembly_procedure_num] assembly_manual not found for {plan_id}"
        )
        return error_response("組立手順がまだ生成されていません", 404)
    steps = assembly_manual if isinstance(assembly_manual, list) else []
    procedure_num = len(steps)
    return jsonify({"num": procedure_num}), 200


# 10_組立手順・3Dモデル取得
@app.route(
    "/api/<plan_id>/assembly_parts/procedure/<int:procedure_no>", methods=["GET"]
)
@require_bearer_token
@require_valid_uuid
def get_assembly_procedure(plan_id, procedure_no):
    if not isinstance(procedure_no, int) or procedure_no < 1:
        return error_response("procedure_noは1以上の整数で指定してください", 400)
    _, bucket = get_gcs_client_and_bucket()
    manual = load_json_from_gcs(bucket, f"{plan_id}/assembly_manual.json")
    if manual is None:
        logging.warning(
            f"[get_assembly_procedure] assembly_manual not found for {plan_id}"
        )
        return error_response("組立手順がまだ生成されていません", 404)
    steps = manual if isinstance(manual, list) else []
    if procedure_no > len(steps):
        return error_response("procedure_noが組立手順数を超えています", 400)
    step_info = steps[procedure_no - 1]
    description = step_info.get("description", "")
    part_names = step_info.get("parts_already_used", [])
    parts3d = load_json_from_gcs(bucket, f"{plan_id}/parts3d.json")
    if parts3d is None:
        logging.warning(
            f"[get_assembly_procedure] parts3d.json not found for {plan_id}"
        )
        return error_response("3D部品位置がまだ生成されていません", 404)
    filtered_parts3d = [p for p in parts3d if p.get("name") in part_names]
    if not filtered_parts3d:
        return error_response("該当手順の部品3D情報が見つかりません", 404)
    obj_text = parts3d_to_obj(filtered_parts3d)
    threading.Thread(target=try_create_manual_pdf, args=(plan_id,), daemon=True).start()
    return (
        jsonify({"step": procedure_no, "description": description, "model": obj_text}),
        200,
    )


# 11_PDF取得可否確認API
@app.route("/api/<plan_id>/manual_pdf/ready", methods=["GET"])
@require_bearer_token
@require_valid_uuid
def manual_pdf_ready(plan_id):
    _, bucket = get_gcs_client_and_bucket()
    pdf_path = f"{plan_id}/design_document.pdf"
    logging.info(
        f"[manual_pdf_ready] Checking GCS for: bucket={bucket.name}, path={pdf_path}"
    )
    ready = gcs_blob_exists(bucket, pdf_path)
    logging.info(f"[manual_pdf_ready] Exists: {ready}")
    return jsonify({"ready": ready}), 200


# 12_PDF取得API
@app.route("/api/<plan_id>/manual_pdf", methods=["GET"])
@require_bearer_token
@require_valid_uuid
@limiter.limit("20 per day")
def get_manual_pdf(plan_id):
    _, bucket = get_gcs_client_and_bucket(GCS_BUCKET_NAME)
    blob = bucket.blob(f"{plan_id}/design_document.pdf")
    if not blob.exists():
        return error_response("指定plan_idが存在しない、またはPDF未生成", 404)
    pdf_bytes = blob.download_as_bytes()
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name="design_document.pdf",
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
