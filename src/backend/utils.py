import uuid
import json
from flask import jsonify, request
from flask import jsonify, request
import functools
import os
import logging
from typing import Optional

ALLOWED_EXTENSIONS = set(
    os.environ.get("ALLOWED_EXTENSIONS", "jpg,jpeg,png").split(",")
)
LOCAL_DATA_DIR = os.environ.get("LOCAL_DATA_DIR", "local_data")
BEARER_TOKEN = os.environ.get("BEARER_TOKEN", "changeme-token")

logger = logging.getLogger("llm_logger")
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def get_local_dir(plan_id):
    dir_path = os.path.join(LOCAL_DATA_DIR, plan_id)
    os.makedirs(dir_path, exist_ok=True)
    return dir_path


def local_file_exists(plan_id, filename):
    file_path = os.path.join(LOCAL_DATA_DIR, plan_id, filename)
    return os.path.exists(file_path)


def load_json_from_local(plan_id, filename):
    file_path = os.path.join(LOCAL_DATA_DIR, plan_id, filename)
    if not os.path.exists(file_path):
        return None
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_uuid(plan_id):
    try:
        uuid_obj = uuid.UUID(plan_id)
        return True
    except ValueError:
        return False


def error_response(message, code=400):
    return jsonify({"error": message}), code


def require_valid_uuid(func):
    @functools.wraps(func)
    def wrapper(plan_id, *args, **kwargs):
        if not validate_uuid(plan_id):
            return error_response("plan_idがUUID形式ではありません", 400)
        return func(plan_id, *args, **kwargs)

    return wrapper


def parts3d_to_obj(parts3d):
    """
    parts3d（部品リスト）からOBJ形式のテキストを生成
    Args:
        parts3d (list[dict]): 3D部品情報リスト
    Returns:
        str: OBJファイル形式のテキスト
    """
    lines = []
    vertex_offset = 1  # OBJの頂点インデックスは1始まり
    for part in parts3d:
        name = part.get("name", "part")
        lines.append(f"g {name}")
        vertices = part.get("vertices", [])
        faces = part.get("faces", [])
        # 頂点リスト
        for v in vertices:
            lines.append(f"v {v['x']} {v['y']} {v['z']}")
        # 面リスト
        for face in faces:
            idxs = face.get("vertices", [])
            # OBJは1始まりなのでオフセットを加算
            idxs1 = [str(i + vertex_offset) for i in idxs]
            lines.append(f"f {' '.join(idxs1)}")
        vertex_offset += len(vertices)
    return "\n".join(lines)


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def upload_to_local(file_stream, plan_id, filename):
    dir_path = get_local_dir(plan_id)
    file_path = os.path.join(dir_path, filename)
    with open(file_path, "wb") as f:
        f.write(file_stream.read())
    return file_path


def require_bearer_token(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return error_response("認証情報がありません", 401)
        token = auth_header.split(" ", 1)[1]
        if token != BEARER_TOKEN:
            return error_response("認証トークンが不正です", 401)
        return func(*args, **kwargs)

    return wrapper


def load_llm_settings():
    """
    LLM設定ファイルを読み込んで返す
    """
    settings_path = os.path.join(
        os.path.dirname(__file__), "settings/llm_settings.json"
    )
    with open(settings_path, "r", encoding="utf-8") as f:
        return json.load(f)


def print_llm_usage_and_cost(
    prompt_tokens: Optional[int],
    output_tokens: Optional[int],
    model: str,
    llm_settings: dict,
):
    """
    トークン数とモデル名から費用を計算し、loggerで出力する
    """
    model_costs = llm_settings["vertex_model_settings"]["model"][model][
        "cost_per_1000_tokens"
    ]
    logger.info(
        f"利用モデル: {model}, 入力トークン数: {prompt_tokens}, 出力トークン数: {output_tokens}"
    )
    input_cost = (prompt_tokens or 0) * model_costs["input"] / 1000
    output_cost = (output_tokens or 0) * model_costs["output"] / 1000
    total_cost = input_cost + output_cost
    logger.info(
        f"推定費用: ${total_cost:.6f} (入力: ${input_cost:.6f}, 出力: ${output_cost:.6f})"
    )
