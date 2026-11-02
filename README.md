# made-audio-novel

เว็บแอปแปลงนิยาย PDF ภาษาไทยเป็นไฟล์เสียง MP3

- ดึงข้อความจาก PDF ด้วย [PyMuPDF](https://pymupdf.readthedocs.io/) และต่อบรรทัดภาษาไทยที่ถูกตัดกลางประโยค
- แปลงเป็นเสียงด้วย [edge-tts](https://github.com/rany2/edge-tts) (เสียงไทย Premwadee / Niwat ไม่ต้องใช้ API key แต่ต้องต่ออินเทอร์เน็ต)
- หน้าเว็บอัปโหลดไฟล์ ดูข้อความ เลือกเสียงและความเร็ว ฟังและดาวน์โหลด MP3

## โครงสร้าง

```
made-audio-novel/
├── app/
│   ├── __init__.py
│   ├── main.py          # FastAPI routes
│   ├── services.py      # ดึงข้อความ PDF + แปลงเสียง
│   └── static/
│       └── index.html   # หน้าเว็บ
├── .env.example
├── .gitignore
├── Dockerfile
├── Procfile
├── requirements.txt
└── README.md
```

## รันในเครื่อง

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # macOS/Linux: cp .env.example .env
uvicorn app.main:app --reload
```

เปิด http://localhost:8000

## รันด้วย Docker

```bash
docker build -t made-audio-novel .
docker run -p 8000:8000 --env-file .env made-audio-novel
```

## API

| Method | Path | คำอธิบาย |
|---|---|---|
| GET | `/health` | ตรวจสถานะ |
| GET | `/api/voices` | รายชื่อเสียงภาษาไทย |
| POST | `/api/extract` | `file` (PDF) → ข้อความที่ดึงได้ |
| POST | `/api/convert` | `file` (PDF), `voice`, `rate` (-50 ถึง 100) → MP3 |

## ข้อจำกัด

- PDF ที่เป็นภาพสแกนยังไม่รองรับ (ต้องทำ OCR ก่อน)
- PDF ที่ฝังฟอนต์ไทยแบบเก่าอาจได้ข้อความเพี้ยน ให้กด "ดูข้อความ" ตรวจก่อนแปลง
- ไฟล์ยาวใช้เวลาแปลงนาน คำขอเดียวต้องรอจนเสร็จ
