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
from ai_modules.parts_detection import detect_parts_from_bytes
from ai_modules.parts_loc_estimate import detect_parts_location_from_bytes
from ai_modules.parts_making import generate_parts_making
from ai_modules.create_assembly_steps import generate_assembly_manual
from ai_modules.agent_chat import run_chat_workflow
import threading
import io
import json
import logging
import base64
import os
from utils import (
    local_file_exists,
    load_json_from_local,
    get_local_dir,
    error_response,
    require_valid_uuid,
    parts3d_to_obj,
    allowed_file,
    upload_to_local,
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
def detect_and_save_parts_list(image_bytes, mime_type, plan_id):
    try:
        logging.info(f"[parts_list] Detection start for plan_id={plan_id}")
        parts_list = detect_parts_from_bytes(image_bytes, mime_type)
        # ローカルに保存
        dir_path = get_local_dir(plan_id)
        with open(os.path.join(dir_path, "parts_list.json"), "w", encoding="utf-8") as f:
            json.dump(parts_list, f, ensure_ascii=False, indent=2)
        logging.info(
            f"[parts_list] Saved to local_data/{plan_id}/parts_list.json"
        )
    except Exception as e:
        logging.error(f"[parts_list detection error] {e}")


# 22_部品3Dモデル作成
def estimate_and_save_parts3d(image_bytes, mime_type, parts_list, plan_id):
    try:
        logging.info(f"[parts3d] Estimation start for plan_id={plan_id}")
        parts3d = detect_parts_location_from_bytes(image_bytes, mime_type, parts_list)
        # ローカルに保存（3D情報）
        dir_path = get_local_dir(plan_id)
        with open(os.path.join(dir_path, "parts3d.json"), "w", encoding="utf-8") as f:
            json.dump(parts3d, f, ensure_ascii=False, indent=2)
        logging.info(f"[parts3d] Saved to local_data/{plan_id}/parts3d.json")
        create_and_save_assembly_manual(
            parts3d, image_bytes, mime_type, plan_id
        )
    except Exception as e:
        logging.error(f"[parts3d estimation error] {e}")


# 23_部品作成手順生成
def create_and_save_parts_manual(parts_list, parts3d, plan_id):
    """parts3dから部品作成手順を生成し、ローカルに保存する"""
    try:
        logging.info(f"[parts_manual] Generating for plan_id={plan_id}")
        parts_manual = generate_parts_making(parts_list, parts3d)
        dir_path = get_local_dir(plan_id)
        with open(os.path.join(dir_path, "parts_manual.json"), "w", encoding="utf-8") as f:
            json.dump(parts_manual, f, ensure_ascii=False, indent=2)
        logging.info(
            f"[parts_manual] Saved to local_data/{plan_id}/parts_manual.json"
        )
    except Exception as e:
        logging.error(f"[parts_manual error] {e}")


# 24_組立手順生成
def create_and_save_assembly_manual(
    parts3d, image_bytes, mime_type, plan_id
):
    """
    parts3d, 画像データ, mime_typeから組立手順を生成し、ローカルに保存する
    """
    try:
        logging.info(f"[assembly_manual] Generating for plan_id={plan_id}")
        assembly_manual = generate_assembly_manual(image_bytes, mime_type, parts3d)
        dir_path = get_local_dir(plan_id)
        with open(os.path.join(dir_path, "assembly_manual.json"), "w", encoding="utf-8") as f:
            json.dump(assembly_manual, f, ensure_ascii=False, indent=2)
        logging.info(
            f"[assembly_manual] Saved to local_data/{plan_id}/assembly_manual.json"
        )
        return assembly_manual
    except Exception as e:
        logging.error(f"[assembly_manual error] {e}")
        return None


def try_create_manual_pdf(plan_id):
    """
    parts_manual.jsonとassembly_manual.jsonが両方存在する場合のみPDF生成
    """
    parts_manual_exists = local_file_exists(plan_id, "parts_manual.json")
    if not parts_manual_exists:
        logging.info(f"[manual_pdf] parts_manual.json not found for {plan_id}")
        return None
    assembly_manual_exists = local_file_exists(plan_id, "assembly_manual.json")
    if not assembly_manual_exists:
        logging.info(f"[manual_pdf] assembly_manual.json not found for {plan_id}")
        return None
    try:
        make_manual_pdf(plan_id)
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
    local_filename = f"image.{ext}"
    try:
        # ファイルをローカルに保存
        file_bytes = file.read()
        file_stream = io.BytesIO(file_bytes)
        upload_to_local(file_stream, plan_id, local_filename)
        logging.info(f"[upload] Image uploaded: {local_filename}")
        # MIMEタイプを決定（content_typeが空の場合は拡張子から推定）
        mime_type = file.content_type
        if not mime_type or mime_type == "application/octet-stream":
            ext_mime_map = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}
            mime_type = ext_mime_map.get(ext, "image/jpeg")
        # 部品検出（2D）はバックグラウンドで実行
        threading.Thread(
            target=detect_and_save_parts_list,
            args=(file_bytes, mime_type, plan_id),
            daemon=True,
        ).start()
        logging.info(
            f"[upload] Started parts_list detection thread for plan_id={plan_id}"
        )
    except Exception as e:
        logging.error(f"[upload error] {e}")
        return jsonify({"error": "保存中にエラーが発生しました"}), 500
    return jsonify({"plan_id": plan_id}), 200


@app.route("/api/<plan_id>/chat", methods=["POST"])
@require_bearer_token
@require_valid_uuid
@limiter.limit("20 per day")
def chat_with_agent(plan_id):
    data = request.json
    user_input = data.get("message", "")
    if not user_input:
        return error_response("メッセージが空です", 400)
    
    parts_list = load_json_from_local(plan_id, "parts_list.json")
    parts3d = load_json_from_local(plan_id, "parts3d.json")
    
    if not parts_list or not parts3d:
        return error_response("部品情報または3Dモデルがまだ生成されていません", 400)
    
    try:
        logging.info(f"[chat] Starting A2A workflow for plan_id={plan_id}")
        result = run_chat_workflow(user_input, parts_list, parts3d)
        
        # 結果をローカルに保存
        dir_path = get_local_dir(plan_id)
        with open(os.path.join(dir_path, "parts_list.json"), "w", encoding="utf-8") as f:
            json.dump(result["parts_list"], f, ensure_ascii=False, indent=2)
        with open(os.path.join(dir_path, "parts3d.json"), "w", encoding="utf-8") as f:
            json.dump(result["parts3d"], f, ensure_ascii=False, indent=2)
            
        # 履歴も保存しておく
        history_path = os.path.join(dir_path, "chat_history.json")
        history = []
        if os.path.exists(history_path):
            with open(history_path, "r", encoding="utf-8") as f:
                history = json.load(f)
        history.append({"user": user_input, "agent_logs": result["agent_logs"]})
        with open(history_path, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
            
        # 画像ファイルを取得して組立手順等も再生成させる
        image_path = None
        ext_found = None
        for ext in ["jpg", "jpeg", "png"]:
            path = os.path.join(dir_path, f"image.{ext}")
            if os.path.exists(path):
                image_path = path
                ext_found = ext
                break
        if image_path is not None:
            with open(image_path, "rb") as f:
                image_bytes = f.read()
            mime_type = f"image/{ext_found}"
            threading.Thread(
                target=create_and_save_parts_manual,
                args=(result["parts_list"], result["parts3d"], plan_id),
                daemon=True,
            ).start()
            threading.Thread(
                target=create_and_save_assembly_manual,
                args=(result["parts3d"], image_bytes, mime_type, plan_id),
                daemon=True,
            ).start()

        return jsonify({
            "message": "モデルの調整が完了しました。",
            "agent_logs": result["agent_logs"],
            "parts_list": result["parts_list"]
        }), 200
    except Exception as e:
        logging.error(f"[chat error] {e}")
        return error_response(f"チャット処理中にエラーが発生しました: {e}", 500)


# 02_部品一覧取得可否確認
@app.route("/api/<plan_id>/parts/ready", methods=["GET"])
@require_bearer_token
@require_valid_uuid
def parts_ready(plan_id):
    ready = local_file_exists(plan_id, "parts_list.json")
    logging.info(f"[parts_ready] Checking parts_list for {plan_id}: {ready}")
    return jsonify({"ready": ready}), 200


# 03_部品一覧取得
@app.route("/api/<plan_id>/parts", methods=["GET"])
@require_bearer_token
@require_valid_uuid
@limiter.limit("15 per day")
def get_parts_list(plan_id):
    parts_list = load_json_from_local(plan_id, "parts_list.json")
    if parts_list is None:
        logging.warning(f"[get_parts_list] parts_list.json not found for {plan_id}")
        return error_response("部品リストがまだ生成されていません", 404)
    # 画像ファイルもローカルから取得
    image_path = None
    ext_found = None
    dir_path = get_local_dir(plan_id)
    for ext in ["jpg", "jpeg", "png"]:
        path = os.path.join(dir_path, f"image.{ext}")
        if os.path.exists(path):
            image_path = path
            ext_found = ext
            break
    if image_path is None:
        logging.warning(f"[get_parts_list] image file not found for {plan_id}")
        return error_response("画像ファイルが見つかりません", 404)
    with open(image_path, "rb") as f:
        image_bytes = f.read()
    mime_type = f"image/{ext_found}"
    threading.Thread(
        target=estimate_and_save_parts3d,
        args=(image_bytes, mime_type, parts_list, plan_id),
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
    ready = local_file_exists(plan_id, "parts3d.json")
    logging.info(f"[model_ready] Checking parts3d for {plan_id}: {ready}")
    return jsonify({"ready": ready}), 200


# 05_3Dモデル情報取得
@app.route("/api/<plan_id>/model", methods=["GET"])
@require_bearer_token
@require_valid_uuid
@limiter.limit("20 per day")
def get_model_obj(plan_id):
    parts_list = load_json_from_local(plan_id, "parts_list.json")
    if parts_list is None:
        logging.warning(f"[get_model_obj] parts_list.json not found for {plan_id}")
        return error_response("部品リストがまだ生成されていません", 404)
    parts3d = load_json_from_local(plan_id, "parts3d.json")
    if parts3d is None:
        logging.warning(f"[get_model_obj] parts3d.json not found for {plan_id}")
        return error_response("3D部品位置がまだ生成されていません", 404)
    obj_text = parts3d_to_obj(parts3d)
    # 画像ファイルもローカルから取得
    image_path = None
    ext_found = None
    dir_path = get_local_dir(plan_id)
    for ext in ["jpg", "jpeg", "png"]:
        path = os.path.join(dir_path, f"image.{ext}")
        if os.path.exists(path):
            image_path = path
            ext_found = ext
            break
    if image_path is None:
        logging.warning(f"[get_model_obj] image file not found for {plan_id}")
        return error_response("画像ファイルが見つかりません", 404)
    with open(image_path, "rb") as f:
        image_bytes = f.read()
    mime_type = f"image/{ext_found}"
    threading.Thread(
        target=create_and_save_parts_manual,
        args=(parts_list, parts3d, plan_id),
        daemon=True,
    ).start()
    threading.Thread(
        target=create_and_save_assembly_manual,
        args=(parts3d, image_bytes, mime_type, plan_id),
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
    ready = local_file_exists(plan_id, "parts_manual.json")
    logging.info(f"[parts_creation_ready] Checking parts_manual for {plan_id}: {ready}")
    return jsonify({"ready": ready}), 200


# 07_部品作成手順一覧取得API
@app.route("/api/<plan_id>/parts_creation", methods=["GET"])
@require_bearer_token
@require_valid_uuid
@limiter.limit("20 per day")
def get_parts_creation(plan_id):
    parts_manual = load_json_from_local(plan_id, "parts_manual.json")
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
    ready = local_file_exists(plan_id, "assembly_manual.json")
    logging.info(
        f"[assembly_manual_ready] Checking assembly_manual for {plan_id}: {ready}"
    )
    return jsonify({"ready": ready}), 200


# 09_組立手順数取得
@app.route("/api/<plan_id>/assembly_parts/procedure_num", methods=["GET"])
@require_bearer_token
@require_valid_uuid
def get_assembly_procedure_num(plan_id):
    assembly_manual = load_json_from_local(plan_id, "assembly_manual.json")
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
    manual = load_json_from_local(plan_id, "assembly_manual.json")
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
    parts3d = load_json_from_local(plan_id, "parts3d.json")
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
    pdf_path = "design_document.pdf"
    ready = local_file_exists(plan_id, pdf_path)
    logging.info(f"[manual_pdf_ready] Exists: {ready}")
    return jsonify({"ready": ready}), 200


# 12_PDF取得API
@app.route("/api/<plan_id>/manual_pdf", methods=["GET"])
@require_bearer_token
@require_valid_uuid
@limiter.limit("20 per day")
def get_manual_pdf(plan_id):
    dir_path = get_local_dir(plan_id)
    pdf_file_path = os.path.join(dir_path, "design_document.pdf")
    if not os.path.exists(pdf_file_path):
        return error_response("指定plan_idが存在しない、またはPDF未生成", 404)
    return send_file(
        pdf_file_path,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="design_document.pdf",
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
