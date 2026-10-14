
import io
import json
from pathlib import Path

import ollama
from fastapi import FastAPI, UploadFile, File, HTTPException
from pypdf import PdfReader

app = FastAPI(title="PRISM API")

MODEL = "llama3.2:3b"

# Struktur data yang diharapkan dari Llama
EXPECTED_SCHEMA = {
    "vendor": None,
    "nama_pengadaan": None,
    "lokasi_pengadaan": None,
    "barang": {
        "rincian": [
            {
                "nama_komponen": None,
                "dalam_negeri": None,
                "luar_negeri": None,
                "total": None,
                "tkdn_persen": None
            }
        ],
        "subtotal_dalam_negeri": None,
        "subtotal_luar_negeri": None,
        "subtotal": None,
        "tkdn_persen": None
    },
    "jasa": {
        "rincian": [
            {
                "nama_komponen": None,
                "dalam_negeri": None,
                "luar_negeri": None,
                "total": None,
                "tkdn_persen": None
            }
        ],
        "subtotal_dalam_negeri": None,
        "subtotal_luar_negeri": None,
        "subtotal": None,
        "tkdn_persen": None
    },
    "komponen_bukan_biaya": None,
    "nilai_penawaran": None
}


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Membaca teks PDF tanpa menyimpan PDF sebagai file baru."""

    reader = PdfReader(io.BytesIO(pdf_bytes))

    pages = []

    for page in reader.pages:
        text = page.extract_text() or ""
        pages.append(text)

    document_text = "\n".join(pages).strip()

    if not document_text:
        raise ValueError(
            "Teks PDF tidak berhasil dibaca. "
            "Dokumen mungkin berupa hasil scan."
        )

    return document_text


def extract_structured_data(document_text: str) -> dict:
    """Memetakan teks PDF menjadi JSON menggunakan Llama."""

    prompt = f"""
Kamu adalah modul ekstraksi dokumen pengadaan untuk PRISM.

Ekstrak data dari dokumen berdasarkan teks sumber.
Jangan mengarang nilai dan jangan menghitung ulang angka.

Aturan:
1. Nilai uang harus berupa integer tanpa pemisah ribuan.
2. Persentase TKDN berupa angka, misalnya 85.47.
3. Gunakan null jika nilai tidak ditemukan.
4. Jangan menganggap nilai yang tidak ditemukan sebagai nol.
5. Pertahankan nama setiap komponen sesuai dokumen.
6. Pisahkan biaya dalam negeri dan luar negeri.
7. Subtotal barang dan subtotal jasa harus diambil
   dari baris subtotal yang sesuai.
8. Nilai penawaran harus berasal dari JUMLAH NILAI PENAWARAN.
9. Rincian barang dan jasa harus berupa array.
10. Kembalikan JSON valid saja, tanpa markdown.

Ikuti struktur JSON ini:
{json.dumps(EXPECTED_SCHEMA, ensure_ascii=False)}

TEKS DOKUMEN:
{document_text}
"""

    response = ollama.chat(
        model=MODEL,
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ],
        format="json",
        options={"temperature": 0}
    )

    raw_result = response["message"]["content"]
    data = json.loads(raw_result)

    if not isinstance(data, dict):
        raise ValueError("Hasil ekstraksi bukan objek JSON.")

    return data


@app.get("/")
def home():
    return {
        "application": "PRISM API",
        "status": "running"
    }


@app.post("/extract")
async def extract_document(file: UploadFile = File(...)):
    """Menerima PDF dan mengembalikan hasil ekstraksi sebagai JSON."""

    if not file.filename or Path(file.filename).suffix.lower() != ".pdf":
        raise HTTPException(
            status_code=400,
            detail="File harus berformat PDF."
        )

    try:
        pdf_bytes = await file.read()

        if not pdf_bytes:
            raise HTTPException(
                status_code=400,
                detail="File PDF kosong."
            )

        document_text = extract_pdf_text(pdf_bytes)
        extracted_data = extract_structured_data(document_text)

        return {
            "filename": file.filename,
            "status": "success",
            "data": extracted_data
        }

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ekstraksi gagal: {str(e)}"
        )

    finally:
        await file.close()
