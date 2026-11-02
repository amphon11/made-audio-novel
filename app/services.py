"""ดึงข้อความจาก PDF และแปลงเป็นเสียงด้วย edge-tts"""

import re

import edge_tts
import pymupdf

THAI_VOICES = {
    "th-TH-PremwadeeNeural": "เปรมวดี (หญิง)",
    "th-TH-NiwatNeural": "นิวัฒน์ (ชาย)",
}

_THAI = "฀-๿"


class PdfError(ValueError):
    pass


def extract_text(pdf_bytes: bytes, max_pages: int) -> tuple[str, int]:
    """คืน (ข้อความ, จำนวนหน้าที่อ่าน)"""
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise PdfError("เปิดไฟล์ PDF ไม่ได้") from exc

    with doc:
        if doc.is_encrypted:
            raise PdfError("PDF ถูกล็อกด้วยรหัสผ่าน")
        pages = min(doc.page_count, max_pages)
        raw = "\n\n".join(doc[i].get_text("text") for i in range(pages))

    text = clean_text(raw)
    if not text:
        raise PdfError("ไม่พบข้อความใน PDF (อาจเป็นไฟล์สแกนที่ต้อง OCR)")
    return text, pages


def clean_text(raw: str) -> str:
    text = raw.replace("\r", "").replace(" ", " ")
    # ภาษาไทยไม่เว้นวรรคระหว่างคำ: ขึ้นบรรทัดใหม่กลางประโยคไทยให้ต่อกันเลย
    text = re.sub(rf"(?<=[{_THAI}])\n(?=[{_THAI}])", "", text)
    # บรรทัดเดี่ยวที่เหลือให้เป็นช่องว่าง ส่วนบรรทัดว่าง (ย่อหน้า) คงไว้
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


async def synthesize(text: str, voice: str, rate: int = 0) -> bytes:
    """แปลงข้อความเป็น MP3; rate เป็นเปอร์เซ็นต์ เช่น -20 ถึง +50"""
    if voice not in THAI_VOICES:
        raise ValueError(f"ไม่รู้จักเสียง {voice}")
    communicate = edge_tts.Communicate(text, voice, rate=f"{rate:+d}%")
    audio = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
    return bytes(audio)
