import io
from typing import List, Optional
import pdfplumber
from pydantic import BaseModel
import ollama

MODEL = "qwen2.5:1.5b"

# 1. Skema Pydantic sesuai struktur JSON Form A5 milikmu
class RincianKomponen(BaseModel):
    nama_komponen: Optional[str] = None
    dalam_negeri: Optional[int] = None
    luar_negeri: Optional[int] = None
    total: Optional[int] = None
    tkdn_persen: Optional[float] = None

class KategoriTKDN(BaseModel):
    rincian: List[RincianKomponen] = []
    subtotal_dalam_negeri: Optional[int] = None
    subtotal_luar_negeri: Optional[int] = None
    subtotal: Optional[int] = None
    tkdn_persen: Optional[float] = None

class FormA5Extraction(BaseModel):
    vendor: Optional[str] = None
    nama_pengadaan: Optional[str] = None
    lokasi_pengadaan: Optional[str] = None
    barang: KategoriTKDN
    jasa: KategoriTKDN
    komponen_bukan_biaya: Optional[int] = None
    nilai_penawaran: Optional[int] = None

# 2. Helper pdfplumber untuk menjaga struktur kolom tabel
def format_page_with_pdfplumber(page) -> str:
    parts = []
    raw_text = page.extract_text() or ""
    if raw_text.strip():
        parts.append(raw_text.strip())

    tables = page.extract_tables() or []
    for idx, table in enumerate(tables, start=1):
        table_lines = [f"\n[Tabel {idx}]"]
        for row in table:
            clean_cells = [str(c).replace("\n", " ").strip() if c else "" for c in row]
            if any(clean_cells):
                table_lines.append(" | ".join(clean_cells))
        parts.append("\n".join(table_lines))

    return "\n\n".join(parts)

# 3. Fungsi utama terpadu: PDF Bytes -> pdfplumber -> Qwen 1.5B -> JSON Valid
def process_form_a5_pdf(file_bytes: bytes) -> dict:
    pages_content = []
    total_pages = 0

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        total_pages = len(pdf.pages)
        for page_num, page in enumerate(pdf.pages, start=1):
            formatted = format_page_with_pdfplumber(page)
            if formatted:
                pages_content.append(f"--- Halaman {page_num} ---\n{formatted}")

    document_text = "\n\n".join(pages_content)

    # Guardrail jika PDF berupa hasil scan gambar tanpa teks
    if len(document_text.strip()) < 30:
        return {
            "status": "gagal",
            "status_validasi": "Needs review",
            "bukti_sumber": "Halaman 1",
            "error": "Teks dokumen kosong atau terdeteksi sebagai PDF hasil scan/gambar.",
            "data": FormA5Extraction(barang=KategoriTKDN(), jasa=KategoriTKDN()).model_dump()
        }

    prompt = f"""Kamu adalah modul ekstraksi dokumen pengadaan untuk sistem PRISM.

Tugasmu memetakan teks dokumen ke JSON terstruktur.
Jangan mengarang data dan jangan menghitung ulang angka.
Ambil angka sesuai yang tertulis di dokumen.

ATURAN:
1. Semua nilai uang berupa integer, tanpa Rp dan pemisah ribuan.
2. Persentase TKDN berupa angka desimal, misalnya 85.47.
3. Jika nilai tidak ditemukan, isi null.
4. Jangan menyamakan subtotal BARANG dengan MATERIAL saja.
5. Jangan menyamakan subtotal JASA dengan satu jenis jasa.
6. Pertahankan nama komponen sebagaimana tertulis di dokumen.
7. Untuk setiap jenis barang dan jasa, pisahkan nilai dalam negeri, luar negeri, total, dan persentase TKDN jika tersedia.
8. Nilai penawaran harus diambil dari JUMLAH NILAI PENAWARAN.

DOKUMEN:
{document_text}"""

    try:
        response = ollama.chat(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            format=FormA5Extraction.model_json_schema(),
            options={
                "temperature": 0,
                "num_ctx": 3072,   # Aman untuk RAM 8 GB
            },
            keep_alive="2m",
        )

        parsed = FormA5Extraction.model_validate_json(response.message.content)

        has_tkdn = (parsed.barang.tkdn_persen is not None) or (parsed.jasa.tkdn_persen is not None)
        is_complete = bool(parsed.vendor and parsed.nilai_penawaran is not None and has_tkdn)
        validation_status = "Validated" if is_complete else "Needs review"

        return {
            "status": "berhasil",
            "status_validasi": validation_status,
            "bukti_sumber": f"Halaman 1-{total_pages}" if total_pages > 1 else "Halaman 1",
            "data": parsed.model_dump()
        }

    except Exception as e:
        return {
            "status": "gagal",
            "status_validasi": "Needs review",
            "error": f"Gagal memproses ekstraksi SLM: {type(e).__name__}"
        }

# 4. Blok uji coba lokal (hapus/abaikan saat di-import ke FastAPI)
if __name__ == "__main__":
    import json

    sample_files = [
        "data/FORM A5 Komitmen TKDN PT Cakar Langit.pdf",
        "data/Form A5 Komitmen TKDN UJE.pdf"
    ]

    for path in sample_files:
        with open(path, "rb") as f:
            hasil = process_form_a5_pdf(f.read())
        print(f"=== Hasil {path} ===")
        print(json.dumps(hasil, indent=2, ensure_ascii=False))