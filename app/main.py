import asyncio
import os
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, File, Form, HTTPException, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from . import __version__, jobs  # noqa: E402
from .services import (  # noqa: E402
    DEMO_TEXT,
    THAI_VOICES,
    PdfError,
    cloudinary_enabled,
    clean_text,
    detect_language,
    extract_text,
    hplt_available,
    ocr_available,
    synthesize,
    translate_to_thai,
    translator_name,
    upload_audio,
)

DEFAULT_VOICE = os.getenv("TTS_VOICE", "th-TH-PremwadeeNeural")
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "20"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "50"))
MAX_CHARS = int(os.getenv("MAX_CHARS", "300000"))

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="made-audio-novel", version=__version__)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

_demo_cache: dict[tuple, bytes] = {}


def _check_voice(voice: str, rate: int, pitch: int, volume: int) -> None:
    if voice not in THAI_VOICES:
        raise HTTPException(400, "เสียงที่เลือกไม่ถูกต้อง")
    if not -50 <= rate <= 100:
        raise HTTPException(400, "ความเร็วต้องอยู่ระหว่าง -50 ถึง 100")
    if not -50 <= pitch <= 50:
        raise HTTPException(400, "ระดับเสียงต้องอยู่ระหว่าง -50 ถึง 50 Hz")
    if not -50 <= volume <= 50:
        raise HTTPException(400, "ความดังต้องอยู่ระหว่าง -50 ถึง 50")


async def _read_pdf(file: UploadFile) -> bytes:
    if not (file.filename or "").lower().endswith((".pdf", ".txt", ".text")):
        raise HTTPException(400, "รองรับเฉพาะไฟล์ .pdf หรือ .txt")
    data = await file.read()
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"ไฟล์ใหญ่เกิน {MAX_UPLOAD_MB} MB")
    return data


async def _read_text_file(file: UploadFile) -> str:
    data = await _read_pdf(file)
    if (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "ไฟล์นี้ไม่ใช่ไฟล์ข้อความ")
    try:
        return clean_text(data.decode("utf-8-sig"))
    except UnicodeDecodeError as exc:
        raise HTTPException(400, "อ่านไฟล์ข้อความไม่ได้ กรุณาบันทึกเป็น UTF-8") from exc


def _job_or_404(job_id: str) -> jobs.Job:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "ไม่พบงานนี้ (อาจหมดอายุแล้ว)")
    return job


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": __version__,
        "translator": translator_name(),
        "hplt_model": hplt_available(),
        "ocr": ocr_available(),
        "cloudinary": cloudinary_enabled(),
    }


@app.get("/api/voices")
def voices():
    return {"default": DEFAULT_VOICE, "voices": THAI_VOICES}


@app.get("/api/voices/{voice}/demo")
async def voice_demo(voice: str, rate: int = 0, pitch: int = 0, volume: int = 0):
    _check_voice(voice, rate, pitch, volume)
    key = (voice, rate, pitch, volume)
    if key not in _demo_cache:
        try:
            _demo_cache[key], _ = await synthesize(DEMO_TEXT, voice, rate, pitch, volume)
        except Exception as exc:
            raise HTTPException(502, f"สร้างเสียงตัวอย่างไม่สำเร็จ: {exc}") from exc
    return Response(_demo_cache[key], media_type="audio/mpeg", headers={"Cache-Control": "max-age=86400"})


@app.post("/api/prepare")
async def prepare(
    file: UploadFile | None = File(None),
    text: str | None = Form(None),
    translate: bool = Form(True),
):
    """อ่าน PDF/ไฟล์ข้อความ หรือรับข้อความที่วางเอง แล้วแปลเป็นไทยตามที่เลือก"""
    if file is not None and text is not None:
        raise HTTPException(400, "กรุณาส่งไฟล์หรือข้อความอย่างใดอย่างหนึ่ง")
    if file is None and not (text or "").strip():
        raise HTTPException(400, "กรุณาเลือกไฟล์หรือวางข้อความ")

    is_text_input = text is not None
    if file is not None:
        filename = (file.filename or "").lower()
        if filename.endswith((".txt", ".text")):
            original = await _read_text_file(file)
            input_kind = "ไฟล์ข้อความ"
        else:
            data = await _read_pdf(file)
            input_kind = "PDF"
    else:
        original = clean_text(text or "")
        input_kind = "ข้อความที่วางเอง"

    if not is_text_input and file is not None and filename.endswith(".pdf"):
        input_kind = "PDF"

    async def work(job: jobs.Job):
        pages, ocr_pages = 1, 0
        if file is not None and filename.endswith(".pdf"):
            job.update("กำลังอ่าน PDF", 1)
            try:
                current_text, pages, ocr_pages = await asyncio.to_thread(
                    extract_text, data, MAX_PAGES, lambda p: job.update("กำลังอ่าน PDF", 1 + p * 14)
                )
            except PdfError as exc:
                raise RuntimeError(str(exc)) from exc
        else:
            current_text = original
            job.update(f"กำลังอ่าน{input_kind}", 15)
        if not current_text:
            raise RuntimeError("ไม่พบข้อความในข้อมูลที่ส่งมา")
        if len(current_text) > MAX_CHARS:
            raise RuntimeError(f"ข้อความยาวเกิน {MAX_CHARS:,} ตัวอักษร")
        language = detect_language(current_text)

        text, translated = current_text, False
        if translate and not is_text_input and language != "th":
            stage = f"กำลังแปลเป็นภาษาไทย ({translator_name()})"
            job.update(stage, 15)
            text = await translate_to_thai(current_text, lambda p: job.update(stage, 15 + p * 85))
            translated = True

        job.result = {
            "pages": pages,
            "ocr_pages": ocr_pages,
            "language": language,
            "translated": translated,
            "translator": translator_name() if translated else None,
            "original": current_text,
            "text": text,
        }

    return jobs.start(work).public()


@app.post("/api/synthesize")
async def synthesize_job(
    text: str = Form(...),
    voice: str = Form(DEFAULT_VOICE),
    rate: int = Form(0),
    pitch: int = Form(0),
    volume: int = Form(0),
    name: str = Form("audio"),
):
    """แปลงข้อความเป็น MP3 ติดตามผลที่ /api/jobs/{id} แล้วโหลดเสียงที่ /api/jobs/{id}/audio"""
    _check_voice(voice, rate, pitch, volume)
    text = text.strip()
    if not text:
        raise HTTPException(400, "ไม่มีข้อความให้แปลงเป็นเสียง")
    if len(text) > MAX_CHARS:
        raise HTTPException(413, f"ข้อความยาวเกิน {MAX_CHARS:,} ตัวอักษร")

    async def work(job: jobs.Job):
        stage = "กำลังแปลงเป็นเสียง"
        job.update(stage, 1)
        upload = cloudinary_enabled()
        scale = 95 if upload else 100
        job.audio, pitch_fallback = await synthesize(
            text, voice, rate, pitch, volume, lambda p: job.update(stage, p * scale)
        )
        job.result = {"size": len(job.audio), "url": None, "pitch_fallback": pitch_fallback}
        if upload:
            job.update("กำลังอัปโหลดขึ้น Cloudinary", 95)
            try:
                job.result["url"] = await upload_audio(job.audio, Path(name).stem)
            except Exception as exc:
                job.result["upload_error"] = f"อัปโหลด Cloudinary ไม่สำเร็จ: {exc}"

    return jobs.start(work).public()


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    return _job_or_404(job_id).public()


@app.get("/api/jobs/{job_id}/audio")
def job_audio(job_id: str, name: str = "audio"):
    job = _job_or_404(job_id)
    if job.status != "done" or job.audio is None:
        raise HTTPException(409, "ไฟล์เสียงยังไม่พร้อม")
    return Response(
        content=job.audio,
        media_type="audio/mpeg",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(Path(name).stem)}.mp3"},
    )
