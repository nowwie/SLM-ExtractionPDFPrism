import os
import logging
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, Form, Header, HTTPException, Depends
from pydantic import BaseModel
from googleapiclient.errors import HttpError

from gdrive_router import process_gdrive_document
from extract_pdf import extract_form_a5_bytes
from extract_excel import extract_excel_bytes

app = FastAPI(title="PRISM AI & Analytics Service")
logger = logging.getLogger(__name__)

API_KEY = os.getenv("PRISM_AI_API_KEY", "prism-secret-key-2026")

def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="API Key tidak valid.")

# --- 1. Ekstraksi via Link Google Drive ---
class GDriveRequest(BaseModel):
    gdrive_url: str
    doc_type: str = "auto"  # "auto" | "oe_historis" | "penawaran_excel" | "form_a5"

@app.post("/api/extract/gdrive", dependencies=[Depends(verify_api_key)])
def extract_from_gdrive(req: GDriveRequest):
    try:
        result = process_gdrive_document(req.gdrive_url, req.doc_type)
        return {
            "status": result.get("status", "success"),
            "source": "gdrive",
            "result": result,
        }
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HttpError as e:
        status_code = e.resp.status
        reason = getattr(e, "reason", "") or "Permintaan Google Drive gagal."
        if status_code == 403:
            detail = (
                f"Akses Google Drive ditolak: {reason} "
                "Pastikan service account sudah diberi akses ke folder."
            )
        elif status_code == 404:
            detail = (
                "Folder/file tidak ditemukan atau belum dibagikan ke service account."
            )
        else:
            detail = f"Google Drive API gagal (HTTP {status_code}): {reason}"
        raise HTTPException(
            status_code=status_code if status_code < 500 else 502,
            detail=detail,
        )
    except Exception as e:
        logger.exception("Gagal memproses dokumen dari Google Drive")
        raise HTTPException(status_code=500, detail=f"Gagal memproses dokumen: {type(e).__name__}: {e}")

# --- 2. Ekstraksi via Upload Langsung (Zero Disk Retention) ---
@app.post("/api/extract/upload", dependencies=[Depends(verify_api_key)])
async def extract_from_upload(
    file: UploadFile = File(...),
    doc_type: str = Form("auto")
):
    file_bytes = await file.read()
    filename = (file.filename or "").lower()

    try:
        if filename.endswith(".pdf") or doc_type == "form_a5":
            result = extract_form_a5_bytes(file_bytes)
        elif filename.endswith((".xlsx", ".xls", ".xlsm")) or doc_type in ("oe_historis", "penawaran_excel"):
            result = extract_excel_bytes(
                file_bytes, 
                filename=file.filename)
        else:
            raise HTTPException(status_code=400, detail="Format file harus PDF atau Excel (.xlsx).")

        return {"status": "success", "source": "upload", "result": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal memproses file: {type(e).__name__}")

# --- 3. Analisis Harga Timpang (Rule-Based) ---
class ItemHargaTimpang(BaseModel):
    kode_item: Optional[str] = None
    nama_item: str
    kategori: Optional[str] = None  # "material" atau "jasa"
    oe_per_unit: float
    harga_penawaran: float

class HargaTimpangRequest(BaseModel):
    items: List[ItemHargaTimpang]
    threshold_persen: float = 110.0  # Acuan default > 110% OE

@app.post("/api/analisis/harga-timpang", dependencies=[Depends(verify_api_key)])
def cek_harga_timpang(req: HargaTimpangRequest):
    hasil_item = []
    jumlah_timpang = 0

    for item in req.items:
        if item.oe_per_unit <= 0:
            rasio_persen = None
            deviasi_persen = None
            is_timpang = False
        else:
            rasio_persen = round((item.harga_penawaran / item.oe_per_unit) * 100, 2)
            deviasi_persen = round(rasio_persen - 100.0, 2)
            is_timpang = rasio_persen > req.threshold_persen

        if is_timpang:
            jumlah_timpang += 1

        hasil_item.append({
            "kode_item": item.kode_item,
            "nama_item": item.nama_item,
            "kategori": item.kategori,
            "oe_per_unit": item.oe_per_unit,
            "harga_penawaran": item.harga_penawaran,
            "rasio_terhadap_oe_persen": rasio_persen,
            "deviasi_persen": deviasi_persen,
            "is_harga_timpang": is_timpang
        })

    return {
        "threshold_persen": req.threshold_persen,
        "total_item": len(hasil_item),
        "total_harga_timpang": jumlah_timpang,
        "items": hasil_item
    }