
import json
import os
import re
import ollama

INPUT_FILE = "data/extracted_pdf.json"
OUTPUT_FILE = "data/llama_extraction.json"
MODEL = "llama3.2:3b"

# Baca hasil ekstraksi teks PDF dari pypdf
with open(INPUT_FILE, "r", encoding="utf-8") as f:
    documents = json.load(f)

results = {}

for file_name, file_data in documents.items():
    print(f"\nMemproses: {file_name}")

    # Gabungkan teks seluruh halaman
    document_text = "\n".join(
        page.get("text") or ""
        for page in file_data.get("pages", [])
    )

    prompt = f"""
Kamu adalah modul ekstraksi dokumen pengadaan untuk sistem PRISM.

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
7. Untuk setiap jenis barang dan jasa, pisahkan nilai dalam negeri,
   luar negeri, total, dan persentase TKDN jika tersedia.
8. Nilai penawaran harus diambil dari JUMLAH NILAI PENAWARAN.
9. Kembalikan JSON valid saja, tanpa markdown atau penjelasan.

Gunakan struktur JSON berikut:

{{
  "vendor": null,
  "nama_pengadaan": null,
  "lokasi_pengadaan": null,
  "barang": {{
    "rincian": [
      {{
        "nama_komponen": null,
        "dalam_negeri": null,
        "luar_negeri": null,
        "total": null,
        "tkdn_persen": null
      }}
    ],
    "subtotal_dalam_negeri": null,
    "subtotal_luar_negeri": null,
    "subtotal": null,
    "tkdn_persen": null
  }},
  "jasa": {{
    "rincian": [
      {{
        "nama_komponen": null,
        "dalam_negeri": null,
        "luar_negeri": null,
        "total": null,
        "tkdn_persen": null
      }}
    ],
    "subtotal_dalam_negeri": null,
    "subtotal_luar_negeri": null,
    "subtotal": null,
    "tkdn_persen": null
  }},
  "komponen_bukan_biaya": null,
  "nilai_penawaran": null
}}

DOKUMEN:
{document_text}
"""

    try:
        response = ollama.chat(
            model=MODEL,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            format="json",
            options={
                "temperature": 0
            }
        )

        raw_result = response["message"]["content"]
        extracted = json.loads(raw_result)

        results[file_name] = {
            "status": "berhasil",
            "data": extracted
        }

        print(json.dumps(
            extracted,
            ensure_ascii=False,
            indent=2
        ))

    except Exception as e:
        results[file_name] = {
            "status": "gagal",
            "error": str(e),
            "raw_text": document_text
        }

        print(f"Gagal memproses {file_name}: {e}")

os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(
        results,
        f,
        ensure_ascii=False,
        indent=2
    )

print(f"\nSelesai. Hasil disimpan di: {OUTPUT_FILE}")
