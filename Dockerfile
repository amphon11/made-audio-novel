FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    HPLT_MODEL_DIR=/app/models/hplt-en-th

# Tesseract OCR สำหรับ PDF ที่เป็นภาพสแกน (ไทย + อังกฤษ)
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-tha tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ดาวน์โหลดและแปลงโมเดลแปล HPLT en→th ตอน build (ราว 80 MB หลังแปลง)
COPY scripts ./scripts
RUN python scripts/prepare_hplt.py "$HPLT_MODEL_DIR"

COPY app ./app

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
