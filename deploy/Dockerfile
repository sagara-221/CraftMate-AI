# Python ベースイメージ
FROM python:3.12

# 必要なライブラリをインストール
# WeasyPrint に必要なパッケージ + 日本語フォント
RUN apt-get update && apt-get install -y \
    build-essential \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libpangocairo-1.0-0 \
    libffi-dev \
    libcairo2 \
    libjpeg-dev \
    libpng-dev \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# Flask 関連ファイルをコピー
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . /app
WORKDIR /app

# ポートを公開
EXPOSE 8080

CMD ["gunicorn", "-b", ":8080", "main:app"]