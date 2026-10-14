# PRISM API Documentation

## 1. Overview

PRISM (Procurement Evaluation System) menggunakan modul ekstraksi dokumen berbasis Python dan Large Language Model (LLM) lokal untuk mengambil informasi dari dokumen pengadaan.

Modul ini bertujuan menghasilkan data terstruktur dari dokumen PDF agar dapat digunakan oleh backend untuk validasi, perhitungan, dan evaluasi vendor.

**Teknologi**
- Python
- FastAPI
- pypdf
- Ollama
- Llama 3.2 3B

## 2. Base URL

Local development:

`http://127.0.0.1:8000`

Interactive API documentation:

`http://127.0.0.1:8000/docs`

## 3. Endpoint

### POST `/extract`

**Description:** Mengunggah dokumen PDF dan mengambil data pengadaan dalam format JSON.

**Content-Type:** `multipart/form-data`

**Request parameter**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `file` | File | Yes | Dokumen PDF yang akan diekstrak |

**Example request**

```bash
curl -X POST "http://127.0.0.1:8000/extract" \
  -F "file=@FORM_A5.pdf"
```

### Success response — HTTP 200

```json
{
  "filename": "FORM_A5.pdf",
  "status": "success",
  "data": {
    "vendor": "CV. CAKAR LANGIT",
    "nama_pengadaan": "Nama pengadaan",
    "lokasi_pengadaan": null,
    "barang": {
      "rincian": [],
      "subtotal_dalam_negeri": null,
      "subtotal_luar_negeri": null,
      "subtotal": null,
      "tkdn_persen": null
    },
    "jasa": {
      "rincian": [],
      "subtotal_dalam_negeri": null,
      "subtotal_luar_negeri": null,
      "subtotal": null,
      "tkdn_persen": null
    },
    "komponen_bukan_biaya": null,
    "nilai_penawaran": null
  }
}
```

Contoh di atas menunjukkan struktur respons, bukan hasil ekstraksi lengkap dari dokumen tertentu. Nilai `null` berarti data belum tersedia atau belum berhasil ditemukan. Array `rincian` berisi komponen yang ditemukan dalam dokumen.

### Detail object barang dan jasa

Setiap elemen dalam `rincian` menggunakan struktur berikut:

```json
{
  "nama_komponen": "Material Langsung",
  "dalam_negeri": 1722962194,
  "luar_negeri": 257454121,
  "total": 1980416315,
  "tkdn_persen": null
}
```

Nilai uang menggunakan integer tanpa simbol mata uang atau pemisah ribuan. Persentase menggunakan angka desimal, misalnya `85.47`.

## 4. Error responses

| HTTP status | Kondisi |
|---|---|
| `400 Bad Request` | File bukan PDF atau file kosong |
| `500 Internal Server Error` | Ekstraksi gagal atau model tidak dapat dipanggil |

Format error mengikuti respons FastAPI, misalnya:

```json
{
  "detail": "File harus berformat PDF."
}
```

## 5. Backend integration

Alur integrasi yang direncanakan:

1. Frontend mengunggah PDF ke endpoint `/extract`.
2. Modul ekstraksi membaca teks PDF menggunakan pypdf.
3. Llama memetakan teks menjadi data JSON terstruktur.
4. Backend memvalidasi kelengkapan dan konsistensi hasil.
5. Data yang valid dapat diteruskan ke penyimpanan dan proses evaluasi PRISM.

## 6. Responsibilities

**AI extraction module**
- Membaca dan memetakan informasi dokumen.
- Menghasilkan data terstruktur.
- Tidak menentukan pemenang vendor.
- Tidak menjadi sumber kebenaran untuk perhitungan finansial.

**Backend**
- Mengelola request dan response API.
- Memvalidasi data hasil ekstraksi.
- Mengelola penyimpanan dan keterkaitan data dengan dokumen sumber.
- Menjalankan perhitungan sesuai aturan bisnis PRISM.
- Menyediakan data untuk frontend.

## 7. Important notes

- Hasil ekstraksi AI harus diperiksa sebelum digunakan dalam evaluasi.
- `null` tidak boleh otomatis dianggap sebagai nol.
- Nilai hasil ekstraksi harus dapat ditelusuri ke dokumen sumber.
- API ini memerlukan Ollama dan model `llama3.2:3b` yang tersedia pada lingkungan backend.
- Dokumentasi ini merupakan rancangan kontrak API dan harus disesuaikan dengan implementasi aktual setelah endpoint diuji.
