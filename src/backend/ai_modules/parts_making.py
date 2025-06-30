from google import genai
from google.genai import types
import json
from utils import load_llm_settings, print_llm_usage_and_cost

llm_settings = load_llm_settings()
func_settings = llm_settings["func_settings"]["parts_making"]
model = func_settings["model"]
temperature = func_settings["temperature"]
top_p = func_settings["top_p"]
seed = func_settings["seed"]
max_output_tokens = func_settings["max_output_tokens"]

with open("sys_prompt/parts_making.txt", "r", encoding="utf-8") as f:
    sys_prompt = f.read()

with open("user_prompt/parts_making.txt", "r", encoding="utf-8") as f:
    user_prompt = f.read()


def generate_parts_making(parts_list: list[dict], parts3d: list[dict]) -> list[dict]:
    """部品情報のdictから作成手順を生成するAIエージェント
    Args:
        parts_list(list): 部品情報のリスト
        parts3d (list[dict]): 部品3D情報リスト
    Returns:
        list[dict]: 部品作成手順情報リスト
    """
    # parts_listのmaterialとshape_noteをparts3dに追加
    parts_info_map = {part["name"]: part for part in parts_list}
    for part in parts3d:
        info = parts_info_map.get(part["name"])
        if info:
            part["material"] = info.get("material")
            part["shape_note"] = info.get("shape_note")
    client = genai.Client(
        vertexai=True,
        project="plan-craft",
        location="global",
    )
    msg_prompt = types.Part.from_text(text=user_prompt)

    msg_parts_json = types.Part.from_text(text=json.dumps(parts3d, ensure_ascii=False))

    system_instruction = [types.Part.from_text(text=sys_prompt)]
    contents = [
        types.Content(
            role="user",
            parts=[msg_prompt, msg_parts_json],
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
        system_instruction=system_instruction,
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
        raise ValueError("部品作成手順書生成AI: レスポンスが空です。")
    if not isinstance(response.text, str):
        raise TypeError(
            f"部品作成手順書生成AI: レスポンスの型が不正です: {type(response.text)}"
        )

    res = json.loads(response.text)
    try:
        data = json.loads(res["response"])
        return data
    except Exception as e:
        raise RuntimeError(
            f"部品作成手順書生成AI:[responseフィールドのJSONデコード失敗] {res['response']}\n{e}"
        )


def generate_from_json(json_path: str) -> None:
    """JSONファイルから部品作成手順を生成し、標準出力に出力する
    Args:
        json_path (str): 部品情報のJSONファイルパス
    """

    with open(json_path, "r", encoding="utf-8") as f:
        part_dict = json.load(f)
    result = generate_parts_making(part_dict)
    print(result)


if __name__ == "__main__":
    # サンプル: 直接呼び出し
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
    parts3d = [
        {
            "name": "天板",
            "type": "cylinder",
            "vertices": [
                {"id": 0, "x": 0.0, "y": 0.0, "z": 42.0},
                {"id": 1, "x": 15.0, "y": 0.0, "z": 42.0},
                {"id": 2, "x": 13.85, "y": 5.74, "z": 42.0},
                {"id": 3, "x": 10.61, "y": 10.61, "z": 42.0},
                {"id": 4, "x": 5.74, "y": 13.85, "z": 42.0},
                {"id": 5, "x": 0.0, "y": 15.0, "z": 42.0},
                {"id": 6, "x": -5.74, "y": 13.85, "z": 42.0},
                {"id": 7, "x": -10.61, "y": 10.61, "z": 42.0},
                {"id": 8, "x": -13.85, "y": 5.74, "z": 42.0},
                {"id": 9, "x": -15.0, "y": 0.0, "z": 42.0},
                {"id": 10, "x": -13.85, "y": -5.74, "z": 42.0},
                {"id": 11, "x": -10.61, "y": -10.61, "z": 42.0},
                {"id": 12, "x": -5.74, "y": -13.85, "z": 42.0},
                {"id": 13, "x": 0.0, "y": -15.0, "z": 42.0},
                {"id": 14, "x": 5.74, "y": -13.85, "z": 42.0},
                {"id": 15, "x": 10.61, "y": -10.61, "z": 42.0},
                {"id": 16, "x": 13.85, "y": -5.74, "z": 42.0},
                {"id": 17, "x": 0.0, "y": 0.0, "z": 45.0},
                {"id": 18, "x": 15.0, "y": 0.0, "z": 45.0},
                {"id": 19, "x": 13.85, "y": 5.74, "z": 45.0},
                {"id": 20, "x": 10.61, "y": 10.61, "z": 45.0},
                {"id": 21, "x": 5.74, "y": 13.85, "z": 45.0},
                {"id": 22, "x": 0.0, "y": 15.0, "z": 45.0},
                {"id": 23, "x": -5.74, "y": 13.85, "z": 45.0},
                {"id": 24, "x": -10.61, "y": 10.61, "z": 45.0},
                {"id": 25, "x": -13.85, "y": 5.74, "z": 45.0},
                {"id": 26, "x": -15.0, "y": 0.0, "z": 45.0},
                {"id": 27, "x": -13.85, "y": -5.74, "z": 45.0},
                {"id": 28, "x": -10.61, "y": -10.61, "z": 45.0},
                {"id": 29, "x": -5.74, "y": -13.85, "z": 45.0},
                {"id": 30, "x": 0.0, "y": -15.0, "z": 45.0},
                {"id": 31, "x": 5.74, "y": -13.85, "z": 45.0},
                {"id": 32, "x": 10.61, "y": -10.61, "z": 45.0},
                {"id": 33, "x": 13.85, "y": -5.74, "z": 45.0},
            ],
            "faces": [
                {"name": "bottom", "vertices": [0, 2, 1]},
                {"name": "bottom", "vertices": [0, 3, 2]},
                {"name": "bottom", "vertices": [0, 4, 3]},
                {"name": "bottom", "vertices": [0, 5, 4]},
                {"name": "bottom", "vertices": [0, 6, 5]},
                {"name": "bottom", "vertices": [0, 7, 6]},
                {"name": "bottom", "vertices": [0, 8, 7]},
                {"name": "bottom", "vertices": [0, 9, 8]},
                {"name": "bottom", "vertices": [0, 10, 9]},
                {"name": "bottom", "vertices": [0, 11, 10]},
                {"name": "bottom", "vertices": [0, 12, 11]},
                {"name": "bottom", "vertices": [0, 13, 12]},
                {"name": "bottom", "vertices": [0, 14, 13]},
                {"name": "bottom", "vertices": [0, 15, 14]},
                {"name": "bottom", "vertices": [0, 16, 15]},
                {"name": "bottom", "vertices": [0, 1, 16]},
                {"name": "top", "vertices": [17, 18, 19]},
                {"name": "top", "vertices": [17, 19, 20]},
                {"name": "top", "vertices": [17, 20, 21]},
                {"name": "top", "vertices": [17, 21, 22]},
                {"name": "top", "vertices": [17, 22, 23]},
                {"name": "top", "vertices": [17, 23, 24]},
                {"name": "top", "vertices": [17, 24, 25]},
                {"name": "top", "vertices": [17, 25, 26]},
                {"name": "top", "vertices": [17, 26, 27]},
                {"name": "top", "vertices": [17, 27, 28]},
                {"name": "top", "vertices": [17, 28, 29]},
                {"name": "top", "vertices": [17, 29, 30]},
                {"name": "top", "vertices": [17, 30, 31]},
                {"name": "top", "vertices": [17, 31, 32]},
                {"name": "top", "vertices": [17, 32, 33]},
                {"name": "top", "vertices": [17, 33, 18]},
                {"name": "side", "vertices": [1, 2, 19, 18]},
                {"name": "side", "vertices": [2, 3, 20, 19]},
                {"name": "side", "vertices": [3, 4, 21, 20]},
                {"name": "side", "vertices": [4, 5, 22, 21]},
                {"name": "side", "vertices": [5, 6, 23, 22]},
                {"name": "side", "vertices": [6, 7, 24, 23]},
                {"name": "side", "vertices": [7, 8, 25, 24]},
                {"name": "side", "vertices": [8, 9, 26, 25]},
                {"name": "side", "vertices": [9, 10, 27, 26]},
                {"name": "side", "vertices": [10, 11, 28, 27]},
                {"name": "side", "vertices": [11, 12, 29, 28]},
                {"name": "side", "vertices": [12, 13, 30, 29]},
                {"name": "side", "vertices": [13, 14, 31, 30]},
                {"name": "side", "vertices": [14, 15, 32, 31]},
                {"name": "side", "vertices": [15, 16, 33, 32]},
                {"name": "side", "vertices": [16, 1, 18, 33]},
            ],
        },
        {
            "name": "脚1",
            "type": "box",
            "vertices": [
                {"id": 0, "x": 14.0, "y": -2.0, "z": 0.0},
                {"id": 1, "x": 18.0, "y": -2.0, "z": 0.0},
                {"id": 2, "x": 18.0, "y": 2.0, "z": 0.0},
                {"id": 3, "x": 14.0, "y": 2.0, "z": 0.0},
                {"id": 4, "x": 8.5, "y": -2.0, "z": 42.0},
                {"id": 5, "x": 12.5, "y": -2.0, "z": 42.0},
                {"id": 6, "x": 12.5, "y": 2.0, "z": 42.0},
                {"id": 7, "x": 8.5, "y": 2.0, "z": 42.0},
            ],
            "faces": [
                {"name": "bottom", "vertices": [0, 1, 2, 3]},
                {"name": "top", "vertices": [7, 6, 5, 4]},
                {"name": "front", "vertices": [0, 1, 5, 4]},
                {"name": "back", "vertices": [3, 2, 6, 7]},
                {"name": "left", "vertices": [0, 3, 7, 4]},
                {"name": "right", "vertices": [1, 2, 6, 5]},
            ],
        },
        {
            "name": "脚2",
            "type": "box",
            "vertices": [
                {"id": 0, "x": -2.0, "y": 14.0, "z": 0.0},
                {"id": 1, "x": 2.0, "y": 14.0, "z": 0.0},
                {"id": 2, "x": 2.0, "y": 18.0, "z": 0.0},
                {"id": 3, "x": -2.0, "y": 18.0, "z": 0.0},
                {"id": 4, "x": -2.0, "y": 8.5, "z": 42.0},
                {"id": 5, "x": 2.0, "y": 8.5, "z": 42.0},
                {"id": 6, "x": 2.0, "y": 12.5, "z": 42.0},
                {"id": 7, "x": -2.0, "y": 12.5, "z": 42.0},
            ],
            "faces": [
                {"name": "bottom", "vertices": [0, 1, 2, 3]},
                {"name": "top", "vertices": [7, 6, 5, 4]},
                {"name": "front", "vertices": [0, 1, 5, 4]},
                {"name": "back", "vertices": [3, 2, 6, 7]},
                {"name": "left", "vertices": [0, 3, 7, 4]},
                {"name": "right", "vertices": [1, 2, 6, 5]},
            ],
        },
        {
            "name": "脚3",
            "type": "box",
            "vertices": [
                {"id": 0, "x": -18.0, "y": -2.0, "z": 0.0},
                {"id": 1, "x": -14.0, "y": -2.0, "z": 0.0},
                {"id": 2, "x": -14.0, "y": 2.0, "z": 0.0},
                {"id": 3, "x": -18.0, "y": 2.0, "z": 0.0},
                {"id": 4, "x": -12.5, "y": -2.0, "z": 42.0},
                {"id": 5, "x": -8.5, "y": -2.0, "z": 42.0},
                {"id": 6, "x": -8.5, "y": 2.0, "z": 42.0},
                {"id": 7, "x": -12.5, "y": 2.0, "z": 42.0},
            ],
            "faces": [
                {"name": "bottom", "vertices": [0, 1, 2, 3]},
                {"name": "top", "vertices": [7, 6, 5, 4]},
                {"name": "front", "vertices": [0, 1, 5, 4]},
                {"name": "back", "vertices": [3, 2, 6, 7]},
                {"name": "left", "vertices": [0, 3, 7, 4]},
                {"name": "right", "vertices": [1, 2, 6, 5]},
            ],
        },
        {
            "name": "脚4",
            "type": "box",
            "vertices": [
                {"id": 0, "x": -2.0, "y": -18.0, "z": 0.0},
                {"id": 1, "x": 2.0, "y": -18.0, "z": 0.0},
                {"id": 2, "x": 2.0, "y": -14.0, "z": 0.0},
                {"id": 3, "x": -2.0, "y": -14.0, "z": 0.0},
                {"id": 4, "x": -2.0, "y": -12.5, "z": 42.0},
                {"id": 5, "x": 2.0, "y": -12.5, "z": 42.0},
                {"id": 6, "x": 2.0, "y": -8.5, "z": 42.0},
                {"id": 7, "x": -2.0, "y": -8.5, "z": 42.0},
            ],
            "faces": [
                {"name": "bottom", "vertices": [0, 1, 2, 3]},
                {"name": "top", "vertices": [7, 6, 5, 4]},
                {"name": "front", "vertices": [0, 1, 5, 4]},
                {"name": "back", "vertices": [3, 2, 6, 7]},
                {"name": "left", "vertices": [0, 3, 7, 4]},
                {"name": "right", "vertices": [1, 2, 6, 5]},
            ],
        },
        {
            "name": "貫1",
            "type": "box",
            "vertices": [
                {"id": 0, "x": -11.9, "y": -1.0, "z": 14.0},
                {"id": 1, "x": 11.9, "y": -1.0, "z": 14.0},
                {"id": 2, "x": 11.9, "y": 1.0, "z": 14.0},
                {"id": 3, "x": -11.9, "y": 1.0, "z": 14.0},
                {"id": 4, "x": -11.9, "y": -1.0, "z": 18.0},
                {"id": 5, "x": 11.9, "y": -1.0, "z": 18.0},
                {"id": 6, "x": 11.9, "y": 1.0, "z": 18.0},
                {"id": 7, "x": -11.9, "y": 1.0, "z": 18.0},
            ],
            "faces": [
                {"name": "bottom", "vertices": [0, 1, 2, 3]},
                {"name": "top", "vertices": [7, 6, 5, 4]},
                {"name": "front", "vertices": [0, 1, 5, 4]},
                {"name": "back", "vertices": [3, 2, 6, 7]},
                {"name": "left", "vertices": [0, 3, 7, 4]},
                {"name": "right", "vertices": [1, 2, 6, 5]},
            ],
        },
        {
            "name": "貫2",
            "type": "box",
            "vertices": [
                {"id": 0, "x": -1.0, "y": -11.9, "z": 14.0},
                {"id": 1, "x": 1.0, "y": -11.9, "z": 14.0},
                {"id": 2, "x": 1.0, "y": 11.9, "z": 14.0},
                {"id": 3, "x": -1.0, "y": 11.9, "z": 14.0},
                {"id": 4, "x": -1.0, "y": -11.9, "z": 18.0},
                {"id": 5, "x": 1.0, "y": -11.9, "z": 18.0},
                {"id": 6, "x": 1.0, "y": 11.9, "z": 18.0},
                {"id": 7, "x": -1.0, "y": 11.9, "z": 18.0},
            ],
            "faces": [
                {"name": "bottom", "vertices": [0, 1, 2, 3]},
                {"name": "top", "vertices": [7, 6, 5, 4]},
                {"name": "front", "vertices": [0, 1, 5, 4]},
                {"name": "back", "vertices": [3, 2, 6, 7]},
                {"name": "left", "vertices": [0, 3, 7, 4]},
                {"name": "right", "vertices": [1, 2, 6, 5]},
            ],
        },
    ]
    print(generate_parts_making(parts3d))
