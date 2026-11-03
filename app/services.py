"""ดึงข้อความจาก PDF (มี OCR), แปลอังกฤษเป็นไทย, แปลงเป็นเสียงด้วย edge-tts และเก็บไฟล์บน Cloudinary"""

import asyncio
import io
import os
import re
import threading
from collections.abc import Callable
from pathlib import Path

import edge_tts
import pymupdf

THAI_VOICES = {
    "th-TH-PremwadeeNeural": "เปรมวดี (หญิง)",
    "th-TH-NiwatNeural": "นิวัฒน์ (ชาย)",
}

DEMO_TEXT = "สวัสดี นี่คือตัวอย่างเสียงอ่านนิยาย กาลครั้งหนึ่งนานมาแล้ว ในหมู่บ้านเล็ก ๆ ริมแม่น้ำ มีเด็กคนหนึ่งชอบฟังนิทานก่อนนอน"

TTS_CHUNK_CHARS = 800
# ยิงขนานมากเกินไปบริการ Edge จะเริ่มตอบ "No audio" (ทดสอบแล้ว 3 กำลังดี)
TTS_CONCURRENCY = int(os.getenv("TTS_CONCURRENCY", "3"))
TRANSLATE_CHUNK_CHARS = {"claude": 6000, "google": 4500}
TRANSLATE_CONCURRENCY = {"claude": 4, "google": 2}
HPLT_BATCH = 16

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
HPLT_MODEL_DIR = Path(os.getenv("HPLT_MODEL_DIR", Path(__file__).parent.parent / "models" / "hplt-en-th"))
OCR_LANGUAGES = os.getenv("OCR_LANGUAGES", "tha+eng")

_THAI = "฀-๿"

Progress = Callable[[float], None]


class PdfError(ValueError):
    pass


class TranslateError(RuntimeError):
    pass


def normalize_thai(text: str) -> str:
    # นิคหิต + สระอา (ํา) ที่บางโมเดล/PDF ให้มา ทำให้ TTS อ่านผิด ต้องรวมเป็นสระอำ (ำ)
    text = text.replace("ํา", "ำ")
    # โมเดลแปลบางครั้งเว้นวรรคก่อนวรรณยุกต์/สระบนล่าง เช่น "แต ่ สิ ่ ง" → "แต่สิ่ง"
    return re.sub(r"[ \t]+([ัิ-ฺ็-๎])[ \t]?", r"\1", text)


# ---------- PDF + OCR ----------

def ocr_available() -> bool:
    try:
        return bool(pymupdf.get_tessdata())
    except Exception:
        return False


def extract_text(pdf_bytes: bytes, max_pages: int, on_progress: Progress | None = None) -> tuple[str, int, int]:
    """คืน (ข้อความ, จำนวนหน้าที่อ่าน, จำนวนหน้าที่ต้อง OCR)"""
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise PdfError("เปิดไฟล์ PDF ไม่ได้") from exc

    with doc:
        if doc.is_encrypted:
            raise PdfError("PDF ถูกล็อกด้วยรหัสผ่าน")
        pages = min(doc.page_count, max_pages)
        can_ocr = ocr_available()
        texts, ocr_pages = [], 0
        for i in range(pages):
            page = doc[i]
            text = page.get_text("text")
            # หน้าที่แทบไม่มีข้อความแต่มีภาพ = หน้าสแกน
            if len(text.strip()) < 20 and page.get_images() and can_ocr:
                tp = page.get_textpage_ocr(language=OCR_LANGUAGES, dpi=300, full=True)
                text = page.get_text("text", textpage=tp)
                ocr_pages += 1
            texts.append(text)
            if on_progress:
                on_progress((i + 1) / pages)

    text = clean_text("\n\n".join(strip_page_furniture(texts)))
    if not text:
        hint = "" if can_ocr else " และเครื่องนี้ไม่มี Tesseract OCR"
        raise PdfError(f"ไม่พบข้อความใน PDF (อาจเป็นไฟล์สแกน{hint})")
    return text, pages, ocr_pages


_PAGE_NUMBER = re.compile(
    r"^[\s\-–—|•·(\[]*(?:(?:page|p\.|หน้า(?:ที่)?)\s*)?[0-9๐-๙ivxlc]{1,6}(?:\s*(?:/|of|จาก)\s*[0-9๐-๙]{1,6})?[\s\-–—|•·)\]]*$",
    re.I,
)
FURNITURE_LINES = 3  # ตรวจหัว/ท้ายกระดาษเฉพาะกี่บรรทัดแรกและท้ายของแต่ละหน้า
FURNITURE_MAX_CHARS = 70  # หัว/ท้ายกระดาษจริงสั้น บรรทัดเนื้อเรื่องเต็มบรรทัดไม่นับ


def _furniture_key(line: str) -> str:
    return re.sub(r"[0-9๐-๙]+", "#", re.sub(r"\s+", " ", line.strip().lower()))


def strip_page_furniture(page_texts: list[str]) -> list[str]:
    """ตัดเลขหน้าและหัว/ท้ายกระดาษที่ซ้ำทุกหน้า (เช่น "ชื่อเรื่อง Page 3 of 10") ไม่ให้ถูกแปลและอ่านออกเสียง"""
    pages = [text.splitlines() for text in page_texts]

    def edge_indexes(lines: list[str]) -> list[int]:
        filled = [i for i, line in enumerate(lines) if line.strip()]
        return sorted(set(filled[:FURNITURE_LINES] + filled[-FURNITURE_LINES:]))

    # บรรทัดขอบหน้าที่หน้าตาเหมือนกัน (ไม่สนตัวเลข) ในครึ่งหนึ่งของหน้าขึ้นไป ถือเป็นหัว/ท้ายกระดาษ
    counts: dict[str, int] = {}
    for lines in pages:
        for key in {_furniture_key(lines[i]) for i in edge_indexes(lines) if len(lines[i].strip()) <= FURNITURE_MAX_CHARS}:
            counts[key] = counts.get(key, 0) + 1
    threshold = max(2, len(pages) / 2)
    repeated = {key for key, n in counts.items() if n >= threshold}

    def is_furniture(line: str) -> bool:
        if _HEADING.match(line):  # หัวบทอยู่ต้นหน้าทุกหน้าได้ ห้ามตัด
            return False
        return _furniture_key(line) in repeated or bool(_PAGE_NUMBER.match(line))

    cleaned = []
    for lines in pages:
        drop = {i for i in edge_indexes(lines) if is_furniture(lines[i])}
        cleaned.append("\n".join(line for i, line in enumerate(lines) if i not in drop))
    return cleaned


_HEADING = re.compile(r"^[ \t]*((?:chapter\b|prologue\b|epilogue\b|part\b|บทที่|ตอนที่|บทนำ|บทส่งท้าย)[^\n]{0,80})$", re.I | re.M)


def clean_text(raw: str) -> str:
    text = normalize_thai(raw.replace("\r", "").replace(" ", " "))
    # หัวบท (Chapter 1 / บทที่ 1) ให้เป็นย่อหน้าของตัวเอง ไม่ให้ไปต่อกับประโยคแรก
    text = _HEADING.sub(r"\n\1\n", text)
    # ภาษาไทยไม่เว้นวรรคระหว่างคำ: ขึ้นบรรทัดใหม่กลางประโยคไทยให้ต่อกันเลย
    text = re.sub(rf"(?<=[{_THAI}])\n(?=[{_THAI}])", "", text)
    # บรรทัดเดี่ยวที่เหลือให้เป็นช่องว่าง ส่วนบรรทัดว่าง (ย่อหน้า) คงไว้
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def detect_language(text: str) -> str:
    thai = len(re.findall(rf"[{_THAI}]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if thai >= latin:
        return "th"
    return "en" if latin else "other"


def split_text(text: str, limit: int) -> list[str]:
    """แบ่งข้อความเป็นก้อนไม่เกิน limit ตัวอักษร โดยตัดที่ย่อหน้า/ประโยคก่อน"""
    pieces: list[str] = []
    for para in text.split("\n\n"):
        while len(para) > limit:
            cut = max(para.rfind(sep, 0, limit) for sep in (". ", "! ", "? ", "” ", " "))
            cut = cut + 1 if cut > limit // 3 else limit
            pieces.append(para[:cut].strip())
            para = para[cut:]
        if para.strip():
            pieces.append(para.strip())

    chunks: list[str] = []
    for piece in pieces:
        if chunks and len(chunks[-1]) + len(piece) + 2 <= limit:
            chunks[-1] += "\n\n" + piece
        else:
            chunks.append(piece)
    return chunks


def _open_quote(text: str) -> bool:
    return text.count('"') % 2 == 1 or text.count("“") > text.count("”")


def split_sentences(paragraph: str, limit: int = 600) -> list[str]:
    parts = re.split(r"(?:(?<=[.!?])|(?<=[.!?][”\"']))\s+(?=[“\"'A-Z0-9(])", paragraph)
    # ไม่ตัดกลางเครื่องหมายคำพูด ไม่งั้นโมเดลแปลประโยคครึ่ง ๆ แล้วใส่สัญลักษณ์แปลก ๆ
    sentences: list[str] = []
    for part in parts:
        if sentences and _open_quote(sentences[-1]) and len(sentences[-1]) < limit:
            sentences[-1] += " " + part
        else:
            sentences.append(part)
    # ประโยคที่ยาวเกินไปสำหรับโมเดล Marian ให้ตัดเพิ่มที่ช่องว่าง
    return [s for sentence in sentences for s in split_text(sentence, limit)]


async def _map_with_progress(items, worker, concurrency: int, on_progress: Progress | None):
    """รัน worker กับทุก item แบบขนาน คืนผลตามลำดับเดิม และรายงานความคืบหน้า 0-1"""
    sem = asyncio.Semaphore(concurrency)
    done = 0

    async def run(item):
        nonlocal done
        async with sem:
            result = await worker(item)
        done += 1
        if on_progress:
            on_progress(done / len(items))
        return result

    return await asyncio.gather(*(run(item) for item in items))


# ---------- Translation ----------

def hplt_available() -> bool:
    return (HPLT_MODEL_DIR / "model.bin").exists() and (HPLT_MODEL_DIR / "model.en-th.spm").exists()


def translator_name() -> str:
    """claude | hplt | google  (ตั้งเองด้วย TRANSLATOR หรือ auto: claude ถ้ามี key, ไม่งั้น hplt ถ้ามีโมเดล)"""
    choice = os.getenv("TRANSLATOR", "auto").lower()
    if choice in ("claude", "hplt", "google"):
        return choice
    if os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"):
        return "claude"
    return "hplt" if hplt_available() else "google"


_CLAUDE_SYSTEM = (
    "You translate novels into natural, fluent Thai for an audiobook narrator. "
    "Keep the meaning, tone, dialogue and paragraph breaks. Transliterate character "
    "and place names into Thai script. Output only the Thai translation, with no notes."
)


async def _translate_claude(chunk: str) -> str:
    import anthropic

    client = anthropic.AsyncAnthropic()
    try:
        response = await client.beta.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=16000,
            output_config={"effort": "medium"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=_CLAUDE_SYSTEM,
            messages=[{"role": "user", "content": chunk}],
        )
    except anthropic.AuthenticationError as exc:
        raise TranslateError("ANTHROPIC_API_KEY ไม่ถูกต้อง") from exc
    except anthropic.RateLimitError as exc:
        raise TranslateError("Claude API ถูกจำกัดอัตรา ลองใหม่ภายหลัง") from exc
    except anthropic.APIStatusError as exc:
        raise TranslateError(f"Claude API ผิดพลาด ({exc.status_code})") from exc
    except anthropic.APIConnectionError as exc:
        raise TranslateError("เชื่อมต่อ Claude API ไม่ได้") from exc

    if response.stop_reason == "refusal":
        raise TranslateError("Claude ปฏิเสธการแปลข้อความบางส่วน")
    return "".join(b.text for b in response.content if b.type == "text").strip()


async def _translate_google(chunk: str) -> str:
    from deep_translator import GoogleTranslator
    from deep_translator.exceptions import TooManyRequests

    try:
        return await asyncio.to_thread(GoogleTranslator(source="auto", target="th").translate, chunk)
    except TooManyRequests as exc:
        raise TranslateError("Google Translate (ฟรี) จำกัดการใช้งานจากเครื่องนี้อยู่ ลองเปลี่ยน TRANSLATOR เป็น hplt") from exc
    except Exception as exc:
        raise TranslateError(f"แปลด้วย Google ไม่สำเร็จ: {exc}") from exc


class _Hplt:
    """โมเดล HPLT en→th (Marian แปลงเป็น CTranslate2) โหลดครั้งเดียวแล้วใช้ซ้ำ"""

    _lock = threading.Lock()
    _instance = None

    def __init__(self):
        import ctranslate2
        import sentencepiece as spm

        self.sp = spm.SentencePieceProcessor(model_file=str(HPLT_MODEL_DIR / "model.en-th.spm"))
        self.translator = ctranslate2.Translator(str(HPLT_MODEL_DIR), device="cpu", compute_type="int8")

    @classmethod
    def get(cls) -> "_Hplt":
        with cls._lock:
            if cls._instance is None:
                if not hplt_available():
                    raise TranslateError("ไม่พบโมเดล HPLT ให้รัน python scripts/prepare_hplt.py ก่อน")
                cls._instance = cls()
            return cls._instance

    def translate(self, sentences: list[str]) -> list[str]:
        results = self.translator.translate_batch(
            [self.sp.encode(s, out_type=str) for s in sentences], beam_size=4, max_decoding_length=512
        )
        return [self.sp.decode(r.hypotheses[0]) for r in results]


async def _translate_hplt(text: str, on_progress: Progress | None) -> str:
    paragraphs = [split_sentences(p) for p in text.split("\n\n") if p.strip()]
    sentences = [s for p in paragraphs for s in p]
    model = await asyncio.to_thread(_Hplt.get)

    translated: list[str] = []
    for i in range(0, len(sentences), HPLT_BATCH):
        translated += await asyncio.to_thread(model.translate, sentences[i : i + HPLT_BATCH])
        if on_progress:
            on_progress(len(translated) / len(sentences))

    out, pos = [], 0
    for para in paragraphs:
        out.append(" ".join(translated[pos : pos + len(para)]))
        pos += len(para)
    return "\n\n".join(out)


async def translate_to_thai(text: str, on_progress: Progress | None = None) -> str:
    name = translator_name()
    if name == "hplt":
        result = await _translate_hplt(text, on_progress)
    else:
        worker = _translate_claude if name == "claude" else _translate_google
        chunks = split_text(text, TRANSLATE_CHUNK_CHARS[name])
        result = "\n\n".join(await _map_with_progress(chunks, worker, TRANSLATE_CONCURRENCY[name], on_progress))
    return normalize_thai(result)


# ---------- Text to speech ----------

TTS_ATTEMPTS = 3


async def _stream_tts(text: str, voice: str, rate: int, pitch: int, volume: int) -> bytes:
    communicate = edge_tts.Communicate(text, voice, rate=f"{rate:+d}%", pitch=f"{pitch:+d}Hz", volume=f"{volume:+d}%")
    audio = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
    return bytes(audio)


async def _synthesize_one(text: str, voice: str, rate: int, pitch: int, volume: int) -> tuple[bytes, bool]:
    """คืน (เสียง, ต้องถอย pitch เป็นปกติหรือไม่)

    บริการของ Edge ตอบ "No audio" แบบสุ่มบ่อย โดยเฉพาะเสียงเปรมวดีที่ปรับ pitch จึงต้องลองซ้ำ
    """
    # ลอง pitch ที่ขอก่อน ถ้าไม่ได้ค่อยถอยเป็น pitch ปกติ (ซึ่งแทบไม่ล้ม)
    plans = [pitch] * TTS_ATTEMPTS + ([0] * TTS_ATTEMPTS if pitch else [])
    for attempt, p in enumerate(plans):
        try:
            return await _stream_tts(text, voice, rate, p, volume), p != pitch
        except edge_tts.exceptions.NoAudioReceived:
            await asyncio.sleep(1.0 * (attempt % TTS_ATTEMPTS + 1))
    raise RuntimeError("บริการเสียงของ Microsoft Edge ไม่ส่งเสียงกลับมา ลองใหม่อีกครั้ง หรือเปลี่ยนเป็นเสียงนิวัฒน์")


def tts_text(text: str) -> str:
    # ตัดสัญลักษณ์ที่ TTS อ่านไม่ได้และทำให้บริการตอบ "No audio"
    return re.sub(r"[·•●▪■◆★☆※¶§|]+", " ", normalize_thai(text))


async def synthesize(
    text: str,
    voice: str,
    rate: int = 0,
    pitch: int = 0,
    volume: int = 0,
    on_progress: Progress | None = None,
) -> tuple[bytes, bool]:
    """แปลงข้อความเป็น MP3; rate/volume เป็น %, pitch เป็น Hz คืน (เสียง, มีบางช่วงที่ใช้ pitch ปกติแทน)"""
    if voice not in THAI_VOICES:
        raise ValueError(f"ไม่รู้จักเสียง {voice}")
    chunks = [c for c in split_text(tts_text(text), TTS_CHUNK_CHARS) if re.search(rf"[{_THAI}A-Za-z0-9]", c)]
    if not chunks:
        raise ValueError("ไม่มีข้อความที่อ่านออกเสียงได้")
    parts = await _map_with_progress(
        chunks, lambda c: _synthesize_one(c, voice, rate, pitch, volume), TTS_CONCURRENCY, on_progress
    )
    # edge-tts ส่ง MP3 frame ดิบที่ bitrate เดียวกัน จึงต่อไฟล์กันตรง ๆ ได้
    return b"".join(audio for audio, _ in parts), any(fallback for _, fallback in parts)


# ---------- Cloudinary ----------

def cloudinary_enabled() -> bool:
    return bool(os.getenv("CLOUDINARY_URL"))


async def upload_audio(audio: bytes, name: str) -> str:
    """อัปโหลด MP3 ขึ้น Cloudinary คืน secure_url (ต้องตั้ง CLOUDINARY_URL)"""
    import cloudinary.uploader

    buffer = io.BytesIO(audio)
    buffer.name = f"{name}.mp3"
    # Cloudinary จัดไฟล์เสียงเป็น resource_type "video" ไม่ใช่ raw
    result = await asyncio.to_thread(
        cloudinary.uploader.upload,
        buffer,
        resource_type="video",
        folder=os.getenv("CLOUDINARY_FOLDER", "made-audio-novel"),
    )
    return result["secure_url"]
