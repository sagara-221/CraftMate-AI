from google import genai
from google.genai import types
import json
import os
from utils import load_llm_settings, print_llm_usage_and_cost

llm_settings = load_llm_settings()
func_settings = llm_settings["func_settings"]["parts_detection"]
model = func_settings["model"]
temperature = func_settings["temperature"]
top_p = func_settings["top_p"]
seed = func_settings["seed"]
max_output_tokens = func_settings["max_output_tokens"]

with open("sys_prompt/parts_detection.txt", "r", encoding="utf-8") as f:
    sys_prompt = f.read()
with open("user_prompt/parts_detection.txt", "r", encoding="utf-8") as f:
    user_prompt = f.read()


def detect_parts_from_bytes(image_bytes: bytes, mime_type: str) -> list[dict]:
    """画像から部品を検出するAIエージェント

    Args:
        image_bytes (bytes): 画像データ
        mime_type (str): 画像のMIMEタイプ

    Returns:
        list[dict]: 検出された部品の情報リスト
    """

    client = genai.Client(
        vertexai=True,
        project="plan-craft",
        location="global",
    )
    msg1_image1 = types.Part.from_bytes(
        data=image_bytes,
        mime_type=mime_type,
    )
    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part.from_text(text=user_prompt),
                msg1_image1,
            ],
        ),
    ]
    generate_content_config = types.GenerateContentConfig(
        temperature=temperature,
        top_p=top_p,
        seed=seed,
        max_output_tokens=max_output_tokens,
        response_mime_type="application/json",
        response_schema={
            "type": "OBJECT",
            "properties": {"response": {"type": "STRING"}},
        },
        system_instruction=[types.Part.from_text(text=sys_prompt)],
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

    if not response.text:
        raise ValueError("部品検出AI: レスポンスが空です。")
    if not isinstance(response.text, str):
        raise TypeError(f"部品検出AI: レスポンスの型が不正です: {type(response.text)}")

    res = json.loads(response.text)
    try:
        data = json.loads(res["response"])
        return data
    except Exception as e:
        raise RuntimeError(
            f"部品検出AI:[responseフィールドのJSONデコード失敗] {res['response']}\n{e}"
        )


def generate(image_path: str) -> None:
    """画像ファイルから部品を検出する
    Args:
        image_path (str): 画像ファイルのパス
    """
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
        data = detect_parts_from_bytes(image_bytes, mime_type)
        print(data)
    except Exception as e:
        print(e)


if __name__ == "__main__":
    generate("images/円椅子.png")
