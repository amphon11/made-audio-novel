# made-audio-novel

เว็บแอปแปลงนิยาย PDF เป็นหนังสือเสียงภาษาไทย (MP3)

- ดึงข้อความจาก PDF ด้วย [PyMuPDF](https://pymupdf.readthedocs.io/) และ OCR หน้าสแกนด้วย Tesseract (ไทย + อังกฤษ)
- แปลอังกฤษ → ไทยอัตโนมัติ เลือกตัวแปลได้ 3 แบบ (ดูด้านล่าง) และตรวจแก้คำแปลบนหน้าเว็บก่อนแปลงเสียง
- แปลงเป็นเสียงด้วย [edge-tts](https://github.com/rany2/edge-tts) เสียงไทย เปรมวดี / นิวัฒน์ ปรับความเร็ว ระดับเสียง ความดังได้ และกดฟังตัวอย่างเสียงก่อนได้
- แสดงความคืบหน้าเป็น % ทั้งตอนอ่าน/แปล และตอนแปลงเสียง
- เก็บไฟล์ MP3 บน [Cloudinary](https://cloudinary.com/documentation/audio_transformations) (ไม่บังคับ)

## ตัวแปลภาษา

| `TRANSLATOR` | ใช้อะไร | หมายเหตุ |
|---|---|---|
| `hplt` | [HPLT en→th](https://huggingface.co/HPLT/translate-en-th-v2.0-hplt_opus) (Marian → CTranslate2 int8, ~80 MB) | ฟรี ออฟไลน์ เร็ว คุณภาพพอใช้ บางประโยคแปลตรงตัว |
| `claude` | Claude API (`claude-opus-5-5`) | แปลนิยายได้ลื่นที่สุด ต้องมี `ANTHROPIC_API_KEY` มีค่าใช้จ่าย |
| `google` | Google Translate แบบฟรีผ่าน deep-translator | ถูกจำกัดอัตราง่าย ไม่แนะนำ |
| `auto` (ค่าเริ่มต้น) | claude ถ้ามี key → hplt ถ้ามีโมเดล → google | |

## โครงสร้าง

```
made-audio-novel/
├── app/
│   ├── __init__.py
│   ├── main.py            # FastAPI routes
│   ├── jobs.py            # งานเบื้องหลัง + progress %
│   ├── services.py        # PDF/OCR, แปลภาษา, TTS, Cloudinary
│   └── static/
│       └── index.html     # หน้าเว็บ
├── scripts/
│   └── prepare_hplt.py    # ดาวน์โหลด + แปลงโมเดล HPLT
├── .env.example
├── .gitignore
├── Dockerfile             # รวม Tesseract + โมเดล HPLT
├── Procfile
├── render.yaml            # Render Blueprint
├── requirements.txt
└── README.md
```

## รันในเครื่อง

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python scripts/prepare_hplt.py  # ครั้งแรกครั้งเดียว ดาวน์โหลด ~300 MB แล้วแปลงเหลือ ~80 MB
copy .env.example .env          # macOS/Linux: cp .env.example .env
uvicorn app.main:app --reload
```

เปิด http://localhost:8000 · เช็กว่าเปิดอะไรอยู่บ้างที่ http://localhost:8000/health

OCR ในเครื่องต้องติดตั้ง [Tesseract](https://github.com/tesseract-ocr/tesseract) พร้อมภาษา `tha` และ `eng` เอง (ใน Docker มีให้แล้ว)

## Deploy บน Render

1. Render Dashboard → **New → Blueprint** → เลือก repo นี้ (ใช้ `render.yaml`)
2. ตั้ง `ANTHROPIC_API_KEY` และ/หรือ `CLOUDINARY_URL` ถ้าต้องการ
3. ใช้ plan ตั้งแต่ Starter ขึ้นไป เพราะ plan ฟรี RAM ไม่พอสำหรับโมเดลแปล + OCR

หรือรัน Docker เอง:

```bash
docker build -t made-audio-novel .
docker run -p 8000:8000 --env-file .env made-audio-novel
```

## API

| Method | Path | คำอธิบาย |
|---|---|---|
| GET | `/health` | สถานะ + ตัวแปลที่ใช้ + มี OCR/Cloudinary ไหม |
| GET | `/api/voices` | รายชื่อเสียงภาษาไทย |
| GET | `/api/voices/{voice}/demo?rate=&pitch=&volume=` | MP3 ตัวอย่างเสียงสั้น ๆ |
| POST | `/api/prepare` | `file` (PDF), `translate` (true/false) → job |
| POST | `/api/synthesize` | `text`, `voice`, `rate` (-50..100), `pitch` (-50..50 Hz), `volume` (-50..50), `name` → job |
| GET | `/api/jobs/{id}` | `status`, `stage`, `progress` (0-100), `result` |
| GET | `/api/jobs/{id}/audio` | ไฟล์ MP3 ของงานที่เสร็จแล้ว |

งานเก็บในหน่วยความจำ 1 ชั่วโมง ถ้าเซิร์ฟเวอร์รีสตาร์ตงานจะหาย (ใช้ Cloudinary ถ้าต้องการเก็บไฟล์ถาวร)

## ข้อจำกัดที่รู้

- เสียงเปรมวดีจากบริการ Edge ตอบช้ากว่านิวัฒน์มาก และเมื่อปรับระดับเสียงมักล้ม ระบบจะลองซ้ำแล้วถอยไปใช้ระดับปกติ พร้อมแจ้งบนหน้าเว็บ
- ยิง TTS ขนานมากเกินไปบริการจะตอบ "No audio" ปรับได้ด้วย `TTS_CONCURRENCY` (ค่าเริ่มต้น 3)
- คำแปลจาก HPLT ควรตรวจแก้ก่อนแปลงเสียง
