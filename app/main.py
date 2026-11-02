import os
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import __version__
from .services import THAI_VOICES, PdfError, extract_text, synthesize

load_dotenv()

DEFAULT_VOICE = os.getenv("TTS_VOICE", "th-TH-PremwadeeNeural")
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "20"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "50"))

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="made-audio-novel", version=__version__)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


async def _read_pdf(file: UploadFile) -> bytes:
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "รองรับเฉพาะไฟล์ .pdf")
    data = await file.read()
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"ไฟล์ใหญ่เกิน {MAX_UPLOAD_MB} MB")
    return data


def _extract(data: bytes) -> tuple[str, int]:
    try:
        return extract_text(data, MAX_PAGES)
    except PdfError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health():
    return {"status": "ok", "version": __version__}


@app.get("/api/voices")
def voices():
    return {"default": DEFAULT_VOICE, "voices": THAI_VOICES}


@app.post("/api/extract")
async def extract(file: UploadFile = File(...)):
    text, pages = _extract(await _read_pdf(file))
    return {"pages": pages, "characters": len(text), "text": text}


@app.post("/api/convert")
async def convert(
    file: UploadFile = File(...),
    voice: str = Form(DEFAULT_VOICE),
    rate: int = Form(0),
):
    if voice not in THAI_VOICES:
        raise HTTPException(400, "เสียงที่เลือกไม่ถูกต้อง")
    if not -50 <= rate <= 100:
        raise HTTPException(400, "ความเร็วต้องอยู่ระหว่าง -50 ถึง 100")

    text, _ = _extract(await _read_pdf(file))
    try:
        audio = await synthesize(text, voice, rate)
    except Exception as exc:
        raise HTTPException(502, f"แปลงเสียงไม่สำเร็จ: {exc}") from exc

    name = Path(file.filename or "audio").stem
    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}.mp3"},
    )
