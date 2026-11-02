"""ดาวน์โหลดโมเดลแปล HPLT en→th (Marian) แล้วแปลงเป็น CTranslate2 int8

ใช้: python scripts/prepare_hplt.py [โฟลเดอร์ปลายทาง]   (ค่าเริ่มต้น models/hplt-en-th)
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

from ctranslate2.converters import MarianConverter
from huggingface_hub import hf_hub_download

REPO = "HPLT/translate-en-th-v2.0-hplt_opus"
FILES = ["model.npz.best-chrf.npz", "model.en-th.spm", "model.en-th.vocab"]


def main(out_dir: Path) -> None:
    if (out_dir / "model.bin").exists() and (out_dir / "model.en-th.spm").exists():
        print(f"มีโมเดลอยู่แล้วที่ {out_dir}")
        return

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp)
        for name in FILES:
            print(f"ดาวน์โหลด {name} ...")
            hf_hub_download(REPO, name, local_dir=src)

        # vocab ของ HPLT เป็นรูปแบบ SentencePiece (token<TAB>score) แต่ตัวแปลงต้องการ Marian yml (token: id)
        tokens = [line.split("\t")[0] for line in (src / "model.en-th.vocab").read_text(encoding="utf-8").splitlines()]
        vocab_yml = src / "vocab.yml"
        with open(vocab_yml, "w", encoding="utf-8") as f:
            for i, token in enumerate(tokens):
                f.write(f"{json.dumps(token, ensure_ascii=False)}: {i}\n")

        print("แปลงเป็น CTranslate2 int8 ...")
        MarianConverter(str(src / FILES[0]), [str(vocab_yml), str(vocab_yml)]).convert(
            str(out_dir), quantization="int8", force=True
        )
        shutil.copy(src / "model.en-th.spm", out_dir / "model.en-th.spm")

    print(f"เสร็จ: {out_dir}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "models/hplt-en-th"))
