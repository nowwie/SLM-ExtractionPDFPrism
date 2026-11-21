import io
import logging
import os
import re
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from typing import Optional

from extract_pdf import extract_form_a5_bytes
from extract_excel import extract_excel_bytes

logger = logging.getLogger(__name__)

SERVICE_ACCOUNT_FILE = "service_account.json"
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

SUPPORTED_MIMES = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.ms-excel": "xlsx",
    "application/vnd.google-apps.spreadsheet": "gsheet",
}


def extract_drive_id(gdrive_url: str) -> str:
    """Menangkap ID baik dari link file (/d/..., id=...) maupun link folder (/folders/...)."""
    match = re.search(r"(?:/folders/|/d/|id=)([a-zA-Z0-9_-]+)", gdrive_url)
    if not match:
        raise ValueError("Format tautan Google Drive tidak valid.")
    return match.group(1)


def get_drive_service():
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        raise FileNotFoundError(
            "File service_account.json tidak ditemukan di folder utama project."
        )
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds)


def download_single_file(service, file_id: str, mime_type: str) -> tuple[bytes, str]:
    """Mengunduh satu file ke RAM (BytesIO) dan mengembalikan (bytes, ekstensi)."""
    buffer = io.BytesIO()

    if mime_type == "application/vnd.google-apps.spreadsheet":
        request = service.files().export_media(
            fileId=file_id,
            mimeType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        ext = "xlsx"
    else:
        request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
        ext = "pdf" if mime_type == "application/pdf" else "xlsx"

    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()

    return buffer.getvalue(), ext


def route_to_extractor(
    file_bytes: bytes,
    ext: str,
    doc_type: str = "auto",
    filename: Optional[str] = None,  
) -> dict:
    if ext == "pdf" or doc_type == "form_a5":
        return extract_form_a5_bytes(file_bytes)
    if ext == "xlsx" or doc_type in ("oe_historis", "penawaran_excel"):
        role = "oe" if doc_type == "oe_historis" else "vendor"
        return extract_excel_bytes(
            file_bytes,
            filename=filename,      
            doc_role=role,         
        )
    raise ValueError(f"Format file tidak didukung: {ext}")


def process_gdrive_document(gdrive_url: str, doc_type: str = "auto") -> dict:
    """Mendukung link 1 file (PDF/Excel/Sheets) maupun link 1 folder Google Drive."""
    drive_id = extract_drive_id(gdrive_url)
    service = get_drive_service()

    meta = (
        service.files()
        .get(fileId=drive_id, fields="id, name, mimeType, driveId", supportsAllDrives=True)
        .execute()
    )
    mime_type = meta.get("mimeType", "")

    # Kasus 1: Input berupa link FOLDER Google Drive
    if mime_type == "application/vnd.google-apps.folder":
        query = f"'{drive_id}' in parents and trashed = false"
        list_args = {
            "q": query,
            "fields": "nextPageToken, files(id, name, mimeType)",
            "pageSize": 100,
            "supportsAllDrives": True,
            "includeItemsFromAllDrives": True,
        }
        if meta.get("driveId"):
            list_args.update(corpora="drive", driveId=meta["driveId"])

        files = []
        page_token = None
        while True:
            if page_token:
                list_args["pageToken"] = page_token
            res = service.files().list(**list_args).execute()
            files.extend(res.get("files", []))
            page_token = res.get("nextPageToken")
            if not page_token:
                break

        processed_files = []
        skipped_files = []
        failed_files = []

        for f in files:
            f_mime = f.get("mimeType", "")
            if f_mime not in SUPPORTED_MIMES:
                skipped_files.append(
                    {"file_name": f.get("name"), "reason": "Format bukan PDF/Excel"}
                )
                continue

            try:
                file_bytes, ext = download_single_file(service, f["id"], f_mime)
                extracted = route_to_extractor(file_bytes, ext, doc_type, filename=f.get("name"))
                processed_files.append(
                    {
                        "file_name": f.get("name"),
                        "file_type": ext,
                        "extraction": extracted,
                    }
                )
            except Exception as e:
                logger.exception("Gagal memproses file Drive %s", f.get("name"))
                failed_files.append(
                    {
                        "file_name": f.get("name"),
                        "error": f"{type(e).__name__}: {e}",
                    }
                )

        return {
            "status": (
                "failed"
                if failed_files and not processed_files
                else "partial" if failed_files else "success"
            ),
            "mode": "folder",
            "folder_name": meta.get("name"),
            "total_processed": len(processed_files),
            "files": processed_files,
            "skipped": skipped_files,
            "failed": failed_files,
        }

    # Kasus 2: Input berupa link 1 FILE Google Drive
    if mime_type not in SUPPORTED_MIMES:
        raise ValueError(
            f"Format file tidak didukung ({mime_type}). Harus PDF atau Excel."
        )

    file_bytes, ext = download_single_file(service, drive_id, mime_type)
    extracted = route_to_extractor(file_bytes, ext, doc_type, filename=meta.get("name"))

    return {
        "mode": "single_file",
        "file_name": meta.get("name"),
        "file_type": ext,
        "extraction": extracted,
    }