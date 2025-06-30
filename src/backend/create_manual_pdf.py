import os
import plotly.graph_objects as go
import plotly.io as pio
import markdown
from weasyprint import HTML
import codecs
from utils import get_gcs_client_and_bucket, load_json_from_gcs, GCS_BUCKET_NAME
import logging

# fontToolsのログをWARNING以上に制限
logging.getLogger("fontTools").setLevel(logging.WARNING)
logging.getLogger("fontTools.ttLib").setLevel(logging.WARNING)
logging.getLogger("fontTools.subset").setLevel(logging.WARNING)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if not logger.hasHandlers():
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def read_files(plan_id: str) -> dict:
    """
    plan_idに基づいてGCSから必要なファイルを読み込む
    Args:
        plan_id (str): UUID形式のplan_id
    Returns:
        dict: 読み込んだファイルの内容を含む辞書
    """
    _, bucket = get_gcs_client_and_bucket(GCS_BUCKET_NAME)

    parts3d = load_json_from_gcs(bucket, f"{plan_id}/parts3d.json")
    parts_manual = load_json_from_gcs(bucket, f"{plan_id}/parts_manual.json")
    assembly_manual = load_json_from_gcs(bucket, f"{plan_id}/assembly_manual.json")
    return {
        "plan_id": plan_id,
        "parts3d": parts3d,
        "parts_manual": parts_manual,
        "assembly_manual": assembly_manual,
    }


def save_parts3d_as_png(parts3d: list[dict], filename="/tmp/output.png"):
    all_x, all_y, all_z = [], [], []
    for part in parts3d:
        if "vertices" in part:
            for v in part["vertices"]:
                all_x.append(v["x"])
                all_y.append(v["y"])
                all_z.append(v["z"])
    min_x = min(all_x) if all_x else 0
    min_y = min(all_y) if all_y else 0
    min_z = min(all_z) if all_z else 0
    fig = go.Figure()
    for part in parts3d:
        if "vertices" in part and "faces" in part:
            xs = [v["x"] - min_x for v in part["vertices"]]
            ys = [v["y"] - min_y for v in part["vertices"]]
            zs = [v["z"] - min_z for v in part["vertices"]]
            i, j, k = [], [], []
            for face in part["faces"]:
                verts = face["vertices"]
                if len(verts) == 3:
                    i.append(verts[0])
                    j.append(verts[1])
                    k.append(verts[2])
                elif len(verts) == 4:
                    i += [verts[0], verts[0]]
                    j += [verts[1], verts[2]]
                    k += [verts[2], verts[3]]
            fig.add_trace(
                go.Mesh3d(
                    x=xs,
                    y=ys,
                    z=zs,
                    i=i,
                    j=j,
                    k=k,
                    opacity=0.5,
                    name=part.get("name", ""),
                )
            )
    fig.update_layout(
        scene=dict(
            xaxis_title="横幅(cm)",
            yaxis_title="縦幅(cm)",
            zaxis_title="高さ(cm)",
            aspectmode="cube",
        ),
        width=700,
        height=700,
        margin=dict(r=10, l=10, b=10, t=10),
        showlegend=False,
    )
    pio.write_image(fig, filename, format="png")


def save_each_part3d_as_png_grouped(
    parts3d: list[dict], parts_manual: list[dict], output_folder: str
):
    desc_to_img = {}
    for part in parts_manual:
        part_names = [
            n.strip() for n in part.get("part_name", "").split(",") if n.strip()
        ]
        filtered_parts = [p for p in parts3d if p.get("name") in part_names]
        if not filtered_parts:
            continue
        # グループ名をファイル名に使う（カンマ区切りを_に変換し、全角文字も許容）
        safe_names = "_".join(
            [
                "".join(
                    c for c in n if c.isalnum() or c in ("_", "-", "脚", "貫", "天板")
                )
                for n in part_names
            ]
        )
        img_filename = f"parts_{safe_names}.png"
        img_path = os.path.join(output_folder, img_filename)
        save_parts3d_as_png(filtered_parts, img_path)
        desc_to_img[",".join(part_names)] = img_filename  # グループ名をキーに
    return desc_to_img


def generate_all_images(parts3d, parts_manual, assembly_manual, output_folder):
    """
    3Dモデル画像・部品画像・組立手順画像を生成し、パス情報を返す
    """
    complete_img_path = f"{output_folder}/complete.png"
    save_parts3d_as_png(parts3d, complete_img_path)
    desc_to_img = save_each_part3d_as_png_grouped(parts3d, parts_manual, output_folder)
    step_img_paths = []
    for assembly_data in assembly_manual:
        step = assembly_data.get("step", 1)
        used_parts = assembly_data.get("parts_already_used", [])
        filtered_parts3d = [p for p in parts3d if p.get("name") in used_parts]
        img_path = f"{output_folder}/step_{step}.png"
        save_parts3d_as_png(filtered_parts3d, img_path)
        step_img_paths.append((step, img_path))
    return complete_img_path, desc_to_img, step_img_paths


def generate_manual_markdown(
    parts_manual,
    assembly_manual,
    complete_img_path,
    desc_to_img,
    step_img_paths,
    output_folder,
):
    """
    Markdownテキストを生成し、ファイルに保存してパスを返す
    """
    lines = []
    lines.append(f"# DIY設計書\n")
    lines.append(f"## 3Dモデル\n")
    lines.append(
        f"![完成3Dモデル]({complete_img_path.replace(output_folder + '/', '')})\n"
    )
    desc_to_parts = {}
    for part in parts_manual:
        desc = part.get("description", "")
        part_names = [
            n.strip() for n in part.get("part_name", "").split(",") if n.strip()
        ]
        group_key = ",".join(part_names)
        desc_to_parts[group_key] = desc
    lines.append(f"\n## 必要な部品\n")
    for group_key, desc in desc_to_parts.items():
        lines.append(f"### {group_key}")
        if group_key in desc_to_img:
            lines.append(
                f"![{group_key}]({desc_to_img[group_key].replace(output_folder + '/', '')})"
            )
        lines.append(desc)
        lines.append("")
    lines.append(f"\n## 組立手順\n")
    for assembly_data, (step, img_path) in zip(assembly_manual, step_img_paths):
        lines.append(f"### 手順{step}")
        lines.append(assembly_data.get("description", ""))
        lines.append(f"![step{step}]({img_path.replace(output_folder + '/', '')})\n")
    output_md_path = f"{output_folder}/manual.md"
    with open(output_md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return output_md_path


def convert_markdown_to_pdf(output_md_path, output_folder):
    """
    MarkdownファイルをPDFに変換し、PDFパスを返す
    """
    pdf_path = os.path.splitext(output_md_path)[0] + ".pdf"
    with codecs.open(output_md_path, "r", encoding="utf-8") as f:
        md_text = f.read()
    html = markdown.markdown(md_text, extensions=["extra", "tables"])
    HTML(string=html, base_url=output_folder).write_pdf(pdf_path)
    return pdf_path


def upload_pdf_to_gcs(pdf_path, bucket, plan_id):
    """
    PDFファイルをGCSにアップロード
    """
    blob = bucket.blob(f"{plan_id}/design_document.pdf")
    with open(pdf_path, "rb") as f:
        blob.upload_from_file(f, content_type="application/pdf")


def cleanup_temp_files(
    pdf_path,
    output_md_path,
    step_img_paths,
    complete_img_path,
    desc_to_img,
    output_folder,
):
    """
    一時ファイル・ディレクトリを削除
    """
    if os.path.exists(pdf_path):
        os.remove(pdf_path)
    if os.path.exists(output_md_path):
        os.remove(output_md_path)
    for _, img_path in step_img_paths:
        if os.path.exists(img_path):
            os.remove(img_path)
    if os.path.exists(complete_img_path):
        os.remove(complete_img_path)
    for rel_img in desc_to_img.values():
        img_path = os.path.join(output_folder, rel_img)
        if os.path.exists(img_path):
            os.remove(img_path)
    try:
        os.rmdir(output_folder)
    except OSError:
        pass


def make_manual_pdf(plan_id: str, bucket_name: str):
    """
    GCSから3つのJSONファイルを取得し、Markdown整形→PDF保存まで行う
    PDFはGCSの {plan_id}/design_document.pdf に保存される
    Args:
        plan_id (str): プランID
        bucket_name (str): GCSバケット名
    """
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("manual_pdf")
    output_folder = f"/tmp/{plan_id}"
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
    input_data = read_files(plan_id)
    parts3d = input_data.get("parts3d", [])
    parts_manual = input_data.get("parts_manual", [])
    assembly_manual = input_data.get("assembly_manual", [])
    # 画像生成
    complete_img_path, desc_to_img, step_img_paths = generate_all_images(
        parts3d, parts_manual, assembly_manual, output_folder
    )
    logger.info(f"PDFに利用する画像生成が完了しました: {output_folder}")
    # Markdown生成
    output_md_path = generate_manual_markdown(
        parts_manual,
        assembly_manual,
        complete_img_path,
        desc_to_img,
        step_img_paths,
        output_folder,
    )
    logger.info(f"Markdownファイルを作成しました: {output_md_path}")
    # PDF生成
    pdf_path = convert_markdown_to_pdf(output_md_path, output_folder)
    logger.info(f"PDFファイルを作成しました: {pdf_path}")
    # GCSへアップロード
    _, bucket = get_gcs_client_and_bucket(bucket_name)
    upload_pdf_to_gcs(pdf_path, bucket, plan_id)
    logger.info(f"PDFファイルをGCSに保存しました: {plan_id}/design_document.pdf")
    # 一時ファイル削除
    cleanup_temp_files(
        pdf_path,
        output_md_path,
        step_img_paths,
        complete_img_path,
        desc_to_img,
        output_folder,
    )
    # logger.info(f"一時ファイルを削除しました")


if __name__ == "__main__":
    plan_id = "749dae63-e297-41bf-82bc-74b5d735b8fd"
    make_manual_pdf(plan_id, GCS_BUCKET_NAME)
