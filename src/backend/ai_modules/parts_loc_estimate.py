from google import genai
from google.genai import types
import os
import json
from utils import load_llm_settings, print_llm_usage_and_cost

llm_settings = load_llm_settings()
func_settings = llm_settings["func_settings"]["parts_loc_estimate"]
model = func_settings["model"]
temperature = func_settings["temperature"]
top_p = func_settings["top_p"]
seed = func_settings["seed"]
max_output_tokens = func_settings["max_output_tokens"]

with open("sys_prompt/parts_loc_estimate.txt", "r", encoding="utf-8") as f:
    sys_prompt = f.read()


def detect_parts_location_from_bytes(
    image_bytes: bytes, mime_type: str, parts_list: list
) -> list[dict]:
    """
    画像バイト列・MIMEタイプ・部品リストから3D情報を推定するAIエージェント
    Args:
        image_bytes (bytes): 画像データ
        mime_type (str): 画像のMIMEタイプ
        parts_list (list): 部品リスト（Pythonリスト）
    Returns:
        list[dict]: 検出された部品の情報リスト
    """
    filtered_parts_list = [
        {k: v for k, v in part.items() if k not in ("material")} for part in parts_list
    ]
    client = genai.Client(
        vertexai=True,
        project="plan-craft",
        location="global",
    )
    msg1_image1 = types.Part.from_bytes(
        data=image_bytes,
        mime_type=mime_type,
    )
    msg1_text1 = types.Part.from_text(
        text=json.dumps(filtered_parts_list, ensure_ascii=False)
    )
    contents = [
        types.Content(role="user", parts=[msg1_image1, msg1_text1]),
    ]
    generate_content_config = types.GenerateContentConfig(
        temperature=temperature,
        top_p=top_p,
        seed=seed,
        max_output_tokens=max_output_tokens,
        system_instruction=[types.Part.from_text(text=sys_prompt)],
        response_mime_type="application/json",
        response_schema={
            "type": "OBJECT",
            "properties": {"response": {"type": "STRING"}},
        },
    )
    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=generate_content_config,
    )
    # トークン数・費用の出力
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        prompt_tokens = getattr(response.usage_metadata, "prompt_token_count", None)
        output_tokens = getattr(response.usage_metadata, "candidates_token_count", None)
        print_llm_usage_and_cost(prompt_tokens, output_tokens, model, llm_settings)
    # 文字列を辞書形式に変換
    if not response.text:
        raise ValueError("3Dモデル生成AI: レスポンスが空です。")
    if not isinstance(response.text, str):
        raise TypeError(
            f"3Dモデル生成AI: レスポンスの型が不正です: {type(response.text)}"
        )
    res = json.loads(response.text)
    try:
        data = json.loads(res["response"])
        return data
    except Exception as e:
        raise RuntimeError(
            f"3Dモデル生成AI:[responseフィールドのJSONデコード失敗] {res['response']}\n{e}"
        )


def generate(image_path, parts_list):
    ext = os.path.splitext(image_path)[1].lower()
    if ext in [".jpg", ".jpeg"]:
        mime_type = "image/jpeg"
    elif ext == ".png":
        mime_type = "image/png"
    else:
        raise ValueError(f"未対応の画像形式です: {ext}")
    with open(image_path, "rb") as image_file:
        image_bytes = image_file.read()
    try:
        data = detect_parts_location_from_bytes(image_bytes, mime_type, parts_list)
        print(data)
    except Exception as e:
        print(e)


if __name__ == "__main__":
    # テスト用
    parts_list = [
        {
            "name": "天板",
            "shape": "円柱",
            "adjacent": ["脚1", "脚2", "脚3", "脚4"],
            "material": "パイン集成材",
            "size": {"radius": 15, "height": 3},
            "shape_note": "縁は丸く面取り加工済み",
        },
        {
            "name": "脚1",
            "shape": "直方体",
            "adjacent": ["天板", "貫1"],
            "material": "パイン材",
            "size": {"width": 4, "depth": 4, "height": 42},
            "shape_note": "天板との接合面は傾斜に合わせて斜めにカット。貫1と接合するためのほぞ穴が1箇所ある。",
        },
        {
            "name": "脚2",
            "shape": "直方体",
            "adjacent": ["天板", "貫2"],
            "material": "パイン材",
            "size": {"width": 4, "depth": 4, "height": 42},
            "shape_note": "天板との接合面は傾斜に合わせて斜めにカット。貫2と接合するためのほぞ穴が1箇所ある。",
        },
        {
            "name": "脚3",
            "shape": "直方体",
            "adjacent": ["天板", "貫1"],
            "material": "パイン材",
            "size": {"width": 4, "depth": 4, "height": 42},
            "shape_note": "天板との接合面は傾斜に合わせて斜めにカット。貫1と接合するためのほぞ穴が1箇所ある。",
        },
        {
            "name": "脚4",
            "shape": "直方体",
            "adjacent": ["天板", "貫2"],
            "material": "パイン材",
            "size": {"width": 4, "depth": 4, "height": 42},
            "shape_note": "天板との接合面は傾斜に合わせて斜めにカット。貫2と接合するためのほぞ穴が1箇所ある。",
        },
        {
            "name": "貫1",
            "shape": "板材",
            "adjacent": ["脚1", "脚3", "貫2"],
            "material": "パイン材",
            "size": {"thickness": 2, "width": 4, "length": 28},
            "shape_note": "中央部に貫2と相欠きで組むための切り欠きがある。両端は脚に差し込むためのほぞ加工済み。",
        },
        {
            "name": "貫2",
            "shape": "板材",
            "adjacent": ["脚2", "脚4", "貫1"],
            "material": "パイン材",
            "size": {"thickness": 2, "width": 4, "length": 28},
            "shape_note": "中央部に貫1と相欠きで組むための切り欠きがある。両端は脚に差し込むためのほぞ加工済み。",
        },
    ]

    generate("images/円椅子.png", parts_list)
