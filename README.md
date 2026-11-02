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

---

## สถานะโปรเจกต์ (อัปเดต 2026-11-02)

**เวอร์ชัน:** V1 · **ยังไม่ได้ deploy** รันในเครื่อง dev เท่านั้น

### ทดสอบแล้ว ใช้ได้

| ส่วน | ผลทดสอบ |
|---|---|
| อ่าน PDF ข้อความ (ไทย/อังกฤษ) + แยกหัวบท | ✅ ผ่าน (`/api/prepare`) |
| แปลอังกฤษ → ไทยด้วย HPLT | ✅ ไฟล์จริง 2 หน้า ~2,500 ตัวอักษร ใช้เวลาไม่กี่วินาที, progress ขยับ 15 → 46 → 77 → 100% บนหน้าเว็บ |
| หน้าเว็บ: อัปโหลด → แปล → แท็บภาษาไทย (แก้ได้) / ต้นฉบับ | ✅ ทดสอบผ่านเบราว์เซอร์ |
| เดโมเสียง (`/api/voices/{voice}/demo`) + cache | ✅ ฝั่ง API |
| แปลงเสียงเป็นงานเบื้องหลัง + progress % + ดาวน์โหลด MP3 | ✅ ฝั่ง API (นิวัฒน์ 3,400 ตัวอักษร ~11 วินาที, เปรมวดี ~70-90 วินาที) |
| pitch / volume + ถอย pitch เมื่อบริการล้ม | ✅ ฝั่ง API |
| ตรวจ input ผิด (ไม่ใช่ PDF, ข้อความว่าง, ค่าเกินช่วง, job ไม่มี) | ✅ |

### ยังไม่ได้ทดสอบ

- ปุ่ม ▶ เดโม และปุ่ม "แปลงเป็นเสียง" **บนหน้าเว็บจริง** (ทดสอบค้างเพราะ server รีโหลดกลางทาง)
- OCR กับ PDF สแกนจริง (เครื่อง dev ไม่มี Tesseract)
- อัปโหลด Cloudinary (ยังไม่มีบัญชี/`CLOUDINARY_URL`)
- `docker build` และ deploy Render (เครื่อง dev ไม่มี Docker)
- แปลด้วย Claude API (ยังไม่มี `ANTHROPIC_API_KEY`)
- PDF ยาวหลายสิบหน้า (เวลา/หน่วยความจำ)

### งานถัดไป (เรียงตามความสำคัญ)

1. ทดสอบ UI ส่วนเดโมเสียงและแปลงเสียงให้จบ
2. `docker build` + deploy Render แล้วทดสอบ OCR บนนั้น
3. ตัดสินใจเรื่องคุณภาพคำแปล: ใช้ Claude (ต้องมี key + ค่าใช้จ่าย) หรืออยู่กับ HPLT
4. ตั้ง Cloudinary ถ้าต้องการลิงก์ไฟล์ถาวร (งานเก็บในหน่วยความจำ หายเมื่อรีสตาร์ต)
5. ทดสอบ PDF ยาว ๆ และพิจารณาเก็บ job ลงดิสก์/คิวถ้ามีผู้ใช้หลายคน
6. ลบข้อความที่ติดมากับ PDF เช่นเลขหน้า/หัวกระดาษ ("AI Passport Page 1 of 2") ก่อนแปล

### การตัดสินใจและเหตุผล

- **HPLT เป็นตัวแปลเริ่มต้น** — ฟรี ออฟไลน์ ไม่ติด rate limit; ไม่มีเวอร์ชัน Hugging Face Transformers จึงแปลงไฟล์ Marian เป็น CTranslate2 เอง (`scripts/prepare_hplt.py`) แทนการคอมไพล์ MarianNMT · OPUS-MT ทางการไม่มี en→th (มีแต่ th→en)
- **ไม่ใช้ Google ฟรีเป็นหลัก** — โดน 429 ตั้งแต่ request แรกจาก IP ของเครื่อง dev
- **Claude เป็นตัวเลือกเสริม** — คุณภาพแปลนิยายดีที่สุด แต่ต้องมี key และมีค่าใช้จ่าย เปิดอัตโนมัติเมื่อมี `ANTHROPIC_API_KEY`
- **TTS แบ่งก้อน 800 ตัวอักษร ขนาน 3** — ขนาน 4-8 ทำให้บริการ Edge ตอบ "No audio"
- **ตัดประโยคไม่ตัดกลางเครื่องหมายคำพูด** — ตัดกลางแล้ว HPLT ใส่สัญลักษณ์แปลก (`·`)
- **`normalize_thai`** — แก้ `ํา` → `ำ` และช่องว่างก่อนวรรณยุกต์ที่ HPLT ใส่มา ไม่งั้น TTS อ่านเพี้ยน
- **Render ผ่าน Docker** — ต้องติดตั้ง `tesseract-ocr-tha` และเตรียมโมเดลตอน build

---

## Handoff สำหรับคนรับงานต่อ

**เริ่มงาน**
1. `git clone https://github.com/amphon11/made-audio-novel.git`
2. ทำตาม [รันในเครื่อง](#รันในเครื่อง) (อย่าลืม `python scripts/prepare_hplt.py`)
3. เปิด `/health` ดูว่า `translator`, `hplt_model`, `ocr`, `cloudinary` เป็นอย่างที่คาดไหม

**อ่านโค้ดตามลำดับนี้**
- `app/main.py` — endpoint ทั้งหมด; `/api/prepare` และ `/api/synthesize` สร้าง job แล้วคืนทันที
- `app/jobs.py` — job เก็บใน dict ในหน่วยความจำ, `job.update(stage, pct)` ใช้รายงาน %
- `app/services.py` — แบ่งเป็นหมวด PDF+OCR / Translation / TTS / Cloudinary ทุกฟังก์ชันยาวรับ `on_progress(0..1)`
- `app/static/index.html` — หน้าเว็บไฟล์เดียว (vanilla JS), `waitJob()` poll `/api/jobs/{id}` ทุก 0.6 วินาที

**ข้อควรระวัง**
- รันด้วย `--reload` แล้วแก้ไฟล์ใน `app/` ระหว่างมีงาน → server รีสตาร์ต งานที่ค้างหายหมด
- ทดสอบ TTS ถี่ ๆ บริการ Edge จะเริ่มปฏิเสธชั่วคราว (ไม่ใช่บั๊กในโค้ด) รอสักพักแล้วลองใหม่
- PDF ทดสอบที่สร้างด้วยฟอนต์มาตรฐาน (Helvetica) เข้ารหัส `“ ”` ไม่ได้ จะออกมาเป็น `·` ใช้ไฟล์จริงทดสอบ
- `models/`, `.venv/`, `.env` ไม่อยู่ใน git

**เครื่อง dev เดิม (Windows)**
- Python 3.14 ที่ `%LOCALAPPDATA%\Programs\Python\Python314`, Git 2.56 ที่ `C:\Program Files\Git`
- ไม่มี Tesseract และ Docker
