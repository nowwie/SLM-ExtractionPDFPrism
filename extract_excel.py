import io
import re
from typing import Optional, Any

import openpyxl


def clean_number(value: Any) -> Optional[float]:
    """
    Konversi angka dengan presisi penuh (tanpa pembulatan) untuk format Indonesia & internasional.
    Mengabaikan string teks campuran seperti tanggal, alamat, atau ukuran pipa (mis. '3/4\"').
    """
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text or text in {"-", "—"}:
        return None

    cleaned_currency = re.sub(r"^(rp\.?|idr|usd|\$)\s*", "", text, flags=re.IGNORECASE)
    cleaned_currency = re.sub(r"\s*(rp\.?|idr|usd|\$)$", "", cleaned_currency, flags=re.IGNORECASE).strip()

    if re.search(r"[a-zA-Z/\"']", cleaned_currency):
        return None

    numeric_text = re.sub(r"[^\d,.\-]", "", cleaned_currency)
    if not numeric_text or numeric_text in {"-", ".", ","}:
        return None

    if "," in numeric_text and "." in numeric_text:
        if numeric_text.rfind(",") > numeric_text.rfind("."):
            numeric_text = numeric_text.replace(".", "").replace(",", ".")
        else:
            numeric_text = numeric_text.replace(",", "")
    elif "," in numeric_text:
        numeric_text = numeric_text.replace(",", ".")
    elif numeric_text.count(".") > 1:
        numeric_text = numeric_text.replace(".", "")

    try:
        return float(numeric_text)
    except ValueError:
        return None


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip().lower()


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def is_company_name(value: Any) -> bool:
    text = normalize_text(value)
    return bool(
        re.search(
            r"\b(pt|cv|ud|firma|persero|koperasi)\.?\s+[a-z]",
            text,
            flags=re.IGNORECASE,
        )
    )


def cell_value(ws, row: int, col: int):
    return ws.cell(row=row, column=col).value


def merged_header_value(ws, row: int, col: int):
    """Membaca nilai header termasuk merged cells."""
    value = cell_value(ws, row, col)
    if value is not None:
        return value

    for merged in ws.merged_cells.ranges:
        if (
            merged.min_row <= row <= merged.max_row
            and merged.min_col <= col <= merged.max_col
        ):
            return cell_value(ws, merged.min_row, merged.min_col)

    return None


# =========================================================
# PEMBACAAN WORKSHEET
# =========================================================

def read_sheet_rows(ws):
    rows = []
    non_empty_count = 0

    for row in ws.iter_rows():
        cells = {}
        for cell in row:
            value = cell.value
            if value is not None and str(value).strip():
                cells[cell.column] = {
                    "value": value,
                    "coordinate": cell.coordinate,
                    "column": cell.column_letter,
                }

        if cells:
            non_empty_count += 1
            rows.append({
                "row_num": row[0].row,
                "cells": cells,
            })

    return rows, non_empty_count


# =========================================================
# DETEKSI HEADER & MAPPING KOLOM GENERIC
# =========================================================

HEADER_WORDS = {
    "kode": ("kode", "code", "no item", "item no", "no.", "no"),
    "nama": (
        "uraian pekerjaan",
        "nama barang",
        "nama item",
        "deskripsi",
        "description",
        "uraian",
        "pekerjaan",
        "barang",
        "jasa",
        "item name",
    ),
    "qty": ("qty", "volume", "quantity", "kuantitas", "vol"),
    "satuan": ("satuan", "unit", "uom", "sat"),
    "spesifikasi": ("spesifikasi", "spek", "specification"),
    "harga": ("harga satuan", "unit price", "harga/unit"),
    "material": ("material",),
    "jasa": ("jasa", "labor", "labour", "upah"),
    "total": ("jumlah harga", "total harga", "subtotal", "total", "jumlah"),
}


def find_header_row(ws, max_scan=50):
    best_row = None
    best_score = 0

    for row_idx in range(1, min(ws.max_row, max_scan) + 1):
        values = []
        for col_idx in range(1, ws.max_column + 1):
            value = merged_header_value(ws, row_idx, col_idx)
            values.append(normalize_text(value))

        joined = " | ".join(value for value in values if value)

        has_name = any(word in joined for word in HEADER_WORDS["nama"])
        has_qty = any(word in joined for word in HEADER_WORDS["qty"])
        has_price = any(
            word in joined
            for word in (
                HEADER_WORDS["harga"]
                + HEADER_WORDS["material"]
                + HEADER_WORDS["jasa"]
                + HEADER_WORDS["total"]
            )
        )

        score = int(has_name) * 3 + int(has_qty) * 2 + int(has_price) * 2
        if has_name and score > best_score:
            best_score = score
            best_row = row_idx

    return best_row


def build_column_mapping(ws, header_row):
    mapping = {}
    start_row = max(1, header_row - 1)
    end_row = min(ws.max_row, header_row + 2)

    for col_idx in range(1, ws.max_column + 1):
        parts = []
        for row_idx in range(start_row, end_row + 1):
            value = merged_header_value(ws, row_idx, col_idx)
            text = normalize_text(value)
            if text and text not in parts:
                parts.append(text)

        combined = " ".join(parts)
        if not combined:
            continue

        col_letter = openpyxl.utils.get_column_letter(col_idx)

        is_unit_price_group = (
            "harga satuan" in combined
            or "unit price" in combined
            or "harga/unit" in combined
        )
        is_total_group = (
            "jumlah harga" in combined
            or "total harga" in combined
            or "subtotal" in combined
            or ("jumlah" in combined and not is_unit_price_group)
            or ("total" in combined and not is_unit_price_group)
        )
        has_material = any(w in combined for w in HEADER_WORDS["material"])
        has_jasa = any(w in combined for w in HEADER_WORDS["jasa"])

        if (
            any(word == combined or word in combined for word in HEADER_WORDS["kode"])
            and not is_unit_price_group
            and not is_total_group
        ):
            if "uraian" not in combined and "nama" not in combined:
                mapping.setdefault("kode", col_letter)

        if (
            any(word in combined for word in HEADER_WORDS["nama"])
            and not is_unit_price_group
            and not is_total_group
        ):
            if combined not in HEADER_WORDS["jasa"]:
                mapping.setdefault("nama", col_letter)

        if any(word in combined for word in HEADER_WORDS["qty"]):
            mapping.setdefault("qty", col_letter)

        if (
            any(word in combined for word in HEADER_WORDS["satuan"])
            and not is_unit_price_group
        ):
            mapping.setdefault("satuan", col_letter)

        if any(word in combined for word in HEADER_WORDS["spesifikasi"]):
            mapping.setdefault("spesifikasi", col_letter)

        if has_material and is_unit_price_group:
            mapping.setdefault("harga_satuan_material", col_letter)
        elif has_jasa and is_unit_price_group:
            mapping.setdefault("harga_satuan_jasa", col_letter)
        elif has_material and is_total_group:
            mapping.setdefault("total_harga_material", col_letter)
        elif has_jasa and is_total_group:
            mapping.setdefault("total_harga_jasa", col_letter)
        elif is_unit_price_group and not has_material and not has_jasa:
            mapping.setdefault("harga_satuan", col_letter)
        elif is_total_group and not has_material and not has_jasa:
            mapping.setdefault("total", col_letter)

    return mapping


# =========================================================
# DETEKSI VENDOR
# =========================================================

def detect_vendor(workbook):
    candidates = []

    for ws in workbook.worksheets:
        if ws.sheet_state != "visible":
            continue

        for row in ws.iter_rows():
            for cell in row:
                value = cell.value
                if not isinstance(value, str):
                    continue
                text = clean_text(value)
                if is_company_name(text):
                    candidates.append({
                        "nama": text,
                        "bukti_sumber": f"{ws.title}!{cell.coordinate}",
                    })

    unique = {}
    for item in candidates:
        key = normalize_text(item["nama"]).replace(".", "")
        unique.setdefault(key, item)

    values = list(unique.values())
    if len(values) == 1:
        return {
            "nama": values[0]["nama"],
            "bukti_sumber": [values[0]["bukti_sumber"]],
            "status": "terdeteksi",
        }
    if len(values) > 1:
        return {
            "nama": None,
            "kandidat": values,
            "status": "perlu_konfirmasi",
        }
    return {
        "nama": None,
        "bukti_sumber": [],
        "status": "tidak_terdeteksi",
    }


# =========================================================
# EKSTRAKSI RINGKASAN BIAYA / SUBTOTAL / FOOTER FINANSIAL
# =========================================================

SUMMARY_KEYWORDS = (
    "subtotal",
    "sub total",
    "total sub jumlah",
    "jumlah harga",
    "total harga",
    "grand total",
    "total +",
    "total+",
    "keuntungan",
    "resiko",
    "risiko",
    "overhead",
    "profit",
    "ppn",
    "pajak",
    "pph",
    "diskon",
    "potongan",
    "pembulatan",
    "terbilang",
)

FOOTER_METADATA_PREFIXES = (
    "cv ",
    "cv.",
    "pt ",
    "pt.",
    "kontraktor",
    "leverensir",
    "direktur",
    "jayapura",
    "jakarta",
    "surabaya",
    "balikpapan",
    "banjarmasin",
    "samarinda",
)


def is_summary_label(text_lower: str) -> bool:
    if text_lower in {"total", "subtotal", "sub total", "jumlah", "grand total"}:
        return True
    return any(text_lower.startswith(kw) or kw in text_lower for kw in SUMMARY_KEYWORDS)


def extract_row_monetary_cells(ws, cells: dict, exclude_cols: set = None) -> list:
    """Mengambil seluruh sel numerik/uang pada baris untuk audit nilai ringkasan."""
    exclude_cols = exclude_cols or set()
    found = []
    for col_idx in sorted(cells.keys()):
        cell_data = cells[col_idx]
        col_letter = cell_data["column"]
        if col_letter in exclude_cols:
            continue
        num = clean_number(cell_data["value"])
        if num is not None:
            found.append({
                "kolom": col_letter,
                "koordinat": f"{ws.title}!{cell_data['coordinate']}",
                "nilai": num,
            })
    return found


def parse_summary_entry(
    ws,
    row_num: int,
    label: str,
    cells: dict,
    mat_col: str = None,
    jasa_col: str = None,
    extra_text_cols: list = None,
) -> dict:
    """Mengekstrak satu baris ringkasan biaya secara utuh tanpa pembulatan."""
    label_clean = clean_text(label)

    def get_col_val(col_letter):
        if not col_letter:
            return None
        col_idx = openpyxl.utils.column_index_from_string(col_letter)
        return cells.get(col_idx, {}).get("value")

    val_mat = clean_number(get_col_val(mat_col))
    val_jasa = clean_number(get_col_val(jasa_col))
    semua_nilai = extract_row_monetary_cells(ws, cells, exclude_cols={"A", "B", "C"})

    teks_tambahan = []
    for col_letter in (extra_text_cols or ["C", "D", "E", "F", "G", "H"]):
        v = get_col_val(col_letter)
        if isinstance(v, str) and clean_text(v) and clean_text(v) not in {":", "%"}:
            teks_tambahan.append(clean_text(v))

    bukti = [
        f"{ws.title}!{cells[col_idx]['coordinate']}"
        for col_idx in sorted(cells.keys())
    ]

    nilai_utama = None
    if val_mat is not None and val_jasa is not None:
        nilai_utama = val_mat + val_jasa
    elif val_jasa is not None:
        nilai_utama = val_jasa
    elif val_mat is not None:
        nilai_utama = val_mat
    elif semua_nilai:
        nilai_utama = semua_nilai[0]["nilai"]

    return {
        "baris": row_num,
        "komponen": label_clean,
        "nilai_material": val_mat,
        "nilai_jasa": val_jasa,
        "nilai_utama": nilai_utama,
        "detail_sel_nilai": semua_nilai,
        "keterangan": " | ".join(teks_tambahan) if teks_tambahan else None,
        "bukti_sumber": bukti,
    }


def build_structured_ringkasan(entries: list) -> dict:
    """Mengelompokkan baris-baris ringkasan menjadi struktur baku + daftar lengkap semua komponen."""
    structured = {
        "subtotals_per_bagian": [],
        "total_sub_jumlah_material": None,
        "total_sub_jumlah_jasa": None,
        "total_sub_jumlah": None,
        "keuntungan_dan_resiko": None,
        "total_sebelum_pembulatan": None,
        "pembulatan": None,
        "selisih_pembulatan": None,
        "ppn": None,
        "grand_total_akhir": None,
        "terbilang": None,
        "semua_baris_ringkasan": entries,
    }

    for e in entries:
        comp = normalize_text(e["komponen"])

        if comp.startswith("subtotal") or comp.startswith("sub total"):
            structured["subtotals_per_bagian"].append(e)
        elif "total sub jumlah" in comp and (
            e["nilai_material"] is not None and e["nilai_jasa"] is not None
        ):
            structured["total_sub_jumlah_material"] = e["nilai_material"]
            structured["total_sub_jumlah_jasa"] = e["nilai_jasa"]
            if structured["total_sub_jumlah"] is None:
                structured["total_sub_jumlah"] = e["nilai_material"] + e["nilai_jasa"]
        elif "total sub jumlah" in comp:
            if e["nilai_utama"] is not None:
                structured["total_sub_jumlah"] = e["nilai_utama"]
        elif (
            "total + keuntungan" in comp
            or "total+keuntungan" in comp
            or "total sebelum pembulatan" in comp
        ):
            structured["total_sebelum_pembulatan"] = e["nilai_utama"]
        elif "keuntungan" in comp or "resiko" in comp or "risiko" in comp:
            structured["keuntungan_dan_resiko"] = e["nilai_utama"]
        elif "pembulatan" in comp:
            structured["pembulatan"] = e["nilai_utama"]
            for s in e["detail_sel_nilai"]:
                if s["nilai"] != e["nilai_utama"]:
                    structured["selisih_pembulatan"] = s["nilai"]
        elif "ppn" in comp:
            structured["ppn"] = e["nilai_utama"]
        elif "terbilang" in comp:
            structured["terbilang"] = e["keterangan"]

    if (
        structured["total_sebelum_pembulatan"] is not None
        and structured["pembulatan"] is not None
        and structured["selisih_pembulatan"] is None
    ):
        structured["selisih_pembulatan"] = (
            structured["total_sebelum_pembulatan"] - structured["pembulatan"]
        )

    if structured["pembulatan"] is not None:
        structured["grand_total_akhir"] = structured["pembulatan"]
    elif structured["total_sebelum_pembulatan"] is not None:
        structured["grand_total_akhir"] = structured["total_sebelum_pembulatan"]
    elif structured["total_sub_jumlah"] is not None:
        structured["grand_total_akhir"] = structured["total_sub_jumlah"]

    return structured


def is_roman_numeral(text: str) -> bool:
    return bool(re.fullmatch(r"[IVXLCDM]+", text.strip(), flags=re.IGNORECASE))


# =========================================================
# EKSTRAKSI KHUSUS BOQ NEGO
# =========================================================

def extract_boq_nego(ws, rows):

    """
    Struktur BOQ Nego (presisi penuh tanpa pembulatan):
    - A/B atau B/C = kode dan nama item
    - L = volume, M = satuan
    - N = harga satuan material, O = harga satuan jasa
    - P = total material, Q = total jasa
    - Menangkap seluruh item pekerjaan, hierarki WBS, sub-rincian lingkup, subtotal bab, & ringkasan akhir.
    """

    header_row = find_header_row(ws) or 9
    items = []
    summary_entries = []
    skipped = []

    current_bab = None
    current_sub_bab = None
    current_kelompok = None
    last_item = None

    for row in rows:
        row_num = row["row_num"]
        cells = row["cells"]

        if row_num <= header_row + 1:
            continue

        def value(col):
            col_idx = openpyxl.utils.column_index_from_string(col)
            return cells.get(col_idx, {}).get("value")

        value_a = value("A")
        value_b = value("B")
        value_c = value("C")
        value_e = value("E")

        def is_text_description(v):
            if not isinstance(v, str):
                return False
            text = v.strip()
            return bool(text) and text not in {"-", "—"}

        # Deteksi baris ringkasan / subtotal / footer biaya
        candidate_label = None
        for col_check in ("A", "B", "C"):
            v_check = value(col_check)
            if isinstance(v_check, str) and clean_text(v_check):
                if is_summary_label(normalize_text(v_check)):
                    candidate_label = clean_text(v_check)
                    break

        if candidate_label is not None:
            summary_entries.append(
                parse_summary_entry(
                    ws=ws,
                    row_num=row_num,
                    label=candidate_label,
                    cells=cells,
                    mat_col="P",
                    jasa_col="Q",
                    extra_text_cols=["C", "D", "E", "F", "G", "H"],
                )
            )
            last_item = None
            continue

        # Deteksi pergeseran kode dan nama
        if is_text_description(value_c):
            kode = value_b
            nama = value_c
            nama_col = "C"
            kode_col = "B"
        elif is_text_description(value_b):
            kode = value_a
            nama = value_b
            nama_col = "B"
            kode_col = "A"
        else:
            # Sub-rincian teknis pada kolom E di bawah item utama
            if is_text_description(value_e) and last_item is not None:
                last_item["rincian_lingkup"].append({
                    "baris": row_num,
                    "deskripsi": clean_text(value_e),
                    "koordinat": f"{ws.title}!E{row_num}",
                })
                skipped.append({
                    "baris": row_num,
                    "alasan": "rincian_lingkup_kolom_e",
                    "teks": clean_text(value_e),
                })
                continue

            # Tangkap jika ada angka uang pada kolom harga/total (N, O, P, Q) di baris tanpa label
            price_cells = [
                c for c in extract_row_monetary_cells(ws, cells)
                if c["kolom"] in {"N", "O", "P", "Q"}
            ]
            if price_cells:
                summary_entries.append(
                    parse_summary_entry(
                        ws=ws,
                        row_num=row_num,
                        label=f"Baris Nilai Tanpa Label (Baris {row_num})",
                        cells=cells,
                        mat_col="P",
                        jasa_col="Q",
                    )
                )
            else:
                skipped.append({
                    "baris": row_num,
                    "alasan": "nama_item_tidak_ditemukan",
                })
            continue

        nama_str = clean_text(nama)
        nama_lower = normalize_text(nama_str)
        kode_str = clean_text(kode) if kode is not None else ""

        if (
            nama_lower.startswith("uraian pekerjaan")
            or any(nama_lower.startswith(p) for p in FOOTER_METADATA_PREFIXES)
            or is_company_name(nama_str)
        ):
            skipped.append({
                "baris": row_num,
                "alasan": "header_atau_metadata_vendor",
            })
            continue

        qty = clean_number(value("L"))
        satuan = value("M")
        harga_material = clean_number(value("N"))
        harga_jasa = clean_number(value("O"))
        total_material = clean_number(value("P"))
        total_jasa = clean_number(value("Q"))

        has_nonzero_price = any(
            v is not None and v != 0.0
            for v in (harga_material, harga_jasa, total_material, total_jasa)
        )
        has_qty_and_unit = (
            qty is not None
            and satuan is not None
            and bool(clean_text(satuan))
        )

        # Baris header hierarki WBS atau sub-rincian lingkup
        if not has_qty_and_unit and not has_nonzero_price:
            if kode_col == "A" and kode_str:
                if is_roman_numeral(kode_str):
                    current_bab = f"{kode_str}. {nama_str}"
                    current_sub_bab = None
                    current_kelompok = None
                else:
                    current_sub_bab = f"{kode_str} {nama_str}"
                    current_kelompok = None
                last_item = None
            elif kode_col == "B" and kode_str and kode_str not in {"-", "—"}:
                current_kelompok = f"{kode_str} {nama_str}"
                last_item = None
            elif last_item is not None and (kode_str in {"", "-", "—"}):
                detail_extra = clean_text(value_e)
                desc_full = f"{nama_str}: {detail_extra}" if detail_extra else nama_str
                last_item["rincian_lingkup"].append({
                    "baris": row_num,
                    "deskripsi": desc_full,
                    "koordinat": f"{ws.title}!{nama_col}{row_num}",
                })

            skipped.append({
                "baris": row_num,
                "alasan": "header_hierarki_atau_rincian_lingkup",
                "teks": nama_str,
            })
            continue

        # Baris item berkuantitas atau bernilai uang -> wajib diekstrak penuh
        source_columns = [kode_col, nama_col, "L", "M", "N", "O", "P", "Q"]
        source_cells = []
        for col in source_columns:
            col_idx = openpyxl.utils.column_index_from_string(col)
            cell_data = cells.get(col_idx)
            if cell_data and cell_data["value"] is not None:
                source_cells.append(f"{ws.title}!{cell_data['coordinate']}")

        status = "tervalidasi"
        if not has_qty_and_unit:
            status = "perlu_review_tanpa_qty_atau_satuan"
        elif total_material is None and total_jasa is None:
            status = "perlu_review_tanpa_total"

        total_harga = None
        if total_material is not None or total_jasa is not None:
            total_harga = (total_material or 0.0) + (total_jasa or 0.0)

        item_obj = {
            "baris": row_num,
            "kode_item": kode_str if kode_str else None,
            "nama_item": nama_str,
            "hierarki": {
                "bab": current_bab,
                "sub_bab": current_sub_bab,
                "kelompok_pekerjaan": current_kelompok,
            },
            "qty": qty,
            "satuan": clean_text(satuan) if satuan is not None and clean_text(satuan) else None,
            "harga_satuan_material": harga_material,
            "harga_satuan_jasa": harga_jasa,
            "total_harga_material": total_material,
            "total_harga_jasa": total_jasa,
            "total_harga": total_harga,
            "rincian_lingkup": [],
            "bukti_sumber": source_cells,
            "status_validasi": status,
        }
        items.append(item_obj)
        last_item = item_obj

    ringkasan = build_structured_ringkasan(summary_entries)

    return {
        "header_row": header_row,
        "column_mapping": {
            "kode": "A/B (dinamis)",
            "nama": "B/C (dinamis)",
            "qty": "L",
            "satuan": "M",
            "harga_satuan_material": "N",
            "harga_satuan_jasa": "O",
            "total_harga_material": "P",
            "total_harga_jasa": "Q",
        },
        "total_items": len(items),
        "items": items,
        "ringkasan_biaya": ringkasan,
        "audit": {
            "baris_terbaca": len(rows),
            "baris_item_diekstrak": len(items),
            "baris_ringkasan_diekstrak": len(summary_entries),
            "baris_dilewati": len(skipped),
            "detail_baris_dilewati": skipped,
        },
    }


# =========================================================
# EKSTRAKSI SHEET REKAPITULASI


def extract_rekapitulasi_sheet(ws, rows):
    """
    Mengekstrak seluruh nilai uang pada sheet Rekapitulasi (per Bab + Ringkasan Akhir)
    tanpa pembulatan.
    """
    header_row = find_header_row(ws) or 13
    rekap_items = []
    summary_entries = []
    skipped = []

    for row in rows:
        row_num = row["row_num"]
        cells = row["cells"]

        if row_num <= header_row + 1:
            continue

        def value(col):
            col_idx = openpyxl.utils.column_index_from_string(col)
            return cells.get(col_idx, {}).get("value")

        val_a = clean_text(value("A"))
        val_b = clean_text(value("B"))

        label = val_b if val_b else val_a
        kode = val_a if val_b else None

        if not label:
            stray_nums = extract_row_monetary_cells(ws, cells)
            if stray_nums:
                summary_entries.append(
                    parse_summary_entry(
                        ws=ws,
                        row_num=row_num,
                        label=f"Baris Nilai (Baris {row_num})",
                        cells=cells,
                        mat_col="I",
                        jasa_col="J",
                    )
                )
            continue

        label_lower = normalize_text(label)

        if (
            any(label_lower.startswith(p) for p in FOOTER_METADATA_PREFIXES)
            or is_company_name(label)
        ):
            skipped.append({
                "baris": row_num,
                "alasan": "metadata_vendor_atau_ttd",
            })
            continue

        if is_summary_label(label_lower):
            summary_entries.append(
                parse_summary_entry(
                    ws=ws,
                    row_num=row_num,
                    label=label,
                    cells=cells,
                    mat_col="I",
                    jasa_col="J",
                    extra_text_cols=["C", "D", "E", "F", "G", "H"],
                )
            )
            continue

        total_mat = clean_number(value("I"))
        total_jasa = clean_number(value("J"))
        semua_nilai = extract_row_monetary_cells(ws, cells, exclude_cols={"A", "B"})

        if total_mat is None and total_jasa is None and not semua_nilai:
            skipped.append({
                "baris": row_num,
                "alasan": "tidak_ada_nilai_uang",
            })
            continue

        total_harga = None
        if total_mat is not None or total_jasa is not None:
            total_harga = (total_mat or 0.0) + (total_jasa or 0.0)
        elif semua_nilai:
            total_harga = sum(x["nilai"] for x in semua_nilai)

        bukti = [
            f"{ws.title}!{cells[col_idx]['coordinate']}"
            for col_idx in sorted(cells.keys())
        ]

        rekap_items.append({
            "baris": row_num,
            "kode_bab": kode if kode else None,
            "uraian_bab": label,
            "total_harga_material": total_mat,
            "total_harga_jasa": total_jasa,
            "total_harga": total_harga,
            "detail_sel_nilai": semua_nilai,
            "bukti_sumber": bukti,
        })

    ringkasan = build_structured_ringkasan(summary_entries)

    return {
        "status": "sheet_rekapitulasi",
        "header_row": header_row,
        "total_items": len(rekap_items),
        "items": rekap_items,
        "ringkasan_biaya": ringkasan,
        "audit": {
            "baris_terbaca": len(rows),
            "baris_rekap_diekstrak": len(rekap_items),
            "baris_ringkasan_diekstrak": len(summary_entries),
            "baris_dilewati": len(skipped),
            "detail_baris_dilewati": skipped,
        },
    }


# =========================================================
# EKSTRAKSI GENERIC UNTUK SHEET LAIN
# =========================================================

def extract_items_from_sheet(ws, rows):
    sheet_lower = normalize_text(ws.title)

    if sheet_lower in {"boq nego", "boq oe", "oe", "rab", "boq"}:
        return extract_boq_nego(ws, rows)

    if "rekapitulasi" in sheet_lower or "rekap" in sheet_lower:
        return extract_rekapitulasi_sheet(ws, rows)

    header_row = find_header_row(ws)
    if header_row is None:
        return None

    mapping = build_column_mapping(ws, header_row)
    if not mapping.get("nama"):
        return None

    items = []
    summary_entries = []
    skipped = []

    for row in rows:
        row_num = row["row_num"]
        if row_num <= header_row:
            continue

        cells = row["cells"]

        def get_value(field):
            col_letter = mapping.get(field)
            if not col_letter:
                return None
            col_idx = openpyxl.utils.column_index_from_string(col_letter)
            return cells.get(col_idx, {}).get("value")

        nama = get_value("nama")
        qty_raw = get_value("qty")
        satuan = get_value("satuan")
        harga = clean_number(get_value("harga_satuan"))
        harga_mat = clean_number(get_value("harga_satuan_material"))
        harga_jasa = clean_number(get_value("harga_satuan_jasa"))
        total_mat = clean_number(get_value("total_harga_material"))
        total_jasa = clean_number(get_value("total_harga_jasa"))
        total = clean_number(get_value("total"))
        qty = clean_number(qty_raw)

        if nama is None or not clean_text(nama):
            alt_label = None
            for col_idx in sorted(cells.keys()):
                v = cells[col_idx]["value"]
                if isinstance(v, str) and clean_text(v) and is_summary_label(normalize_text(v)):
                    alt_label = clean_text(v)
                    break
            if alt_label:
                summary_entries.append(
                    parse_summary_entry(
                        ws=ws,
                        row_num=row_num,
                        label=alt_label,
                        cells=cells,
                        mat_col=mapping.get("total_harga_material"),
                        jasa_col=mapping.get("total_harga_jasa") or mapping.get("total"),
                    )
                )
            continue

        nama_str = clean_text(nama)
        nama_lower = normalize_text(nama_str)

        if nama_lower in {"-", "—"}:
            skipped.append({
                "baris": row_num,
                "alasan": "nama_item_kosong_atau_strip",
            })
            continue

        if any(nama_lower.startswith(p) for p in FOOTER_METADATA_PREFIXES) or (
            is_company_name(nama_str) and qty is None
        ):
            skipped.append({
                "baris": row_num,
                "alasan": "terindikasi_metadata_vendor",
            })
            continue

        if qty is None and is_summary_label(nama_lower):
            summary_entries.append(
                parse_summary_entry(
                    ws=ws,
                    row_num=row_num,
                    label=nama_str,
                    cells=cells,
                    mat_col=mapping.get("total_harga_material"),
                    jasa_col=mapping.get("total_harga_jasa") or mapping.get("total"),
                )
            )
            continue

        has_numeric_data = any(
            v is not None
            for v in (qty, harga, harga_mat, harga_jasa, total_mat, total_jasa, total)
        )

        if not has_numeric_data:
            skipped.append({
                "baris": row_num,
                "alasan": "tidak_ada_data_kuantitas_atau_harga",
            })
            continue

        source_cells = []
        for field in (
            "kode",
            "nama",
            "spesifikasi",
            "qty",
            "satuan",
            "harga_satuan",
            "harga_satuan_material",
            "harga_satuan_jasa",
            "total_harga_material",
            "total_harga_jasa",
            "total",
        ):
            col_letter = mapping.get(field)
            if not col_letter:
                continue
            col_idx = openpyxl.utils.column_index_from_string(col_letter)
            cell_data = cells.get(col_idx)
            if cell_data and cell_data["value"] is not None:
                source_cells.append(f"{ws.title}!{cell_data['coordinate']}")

        if total is None and (total_mat is not None or total_jasa is not None):
            total = (total_mat or 0.0) + (total_jasa or 0.0)

        status = "tervalidasi"
        if qty is None:
            status = "perlu_review_tanpa_qty"
        elif not satuan:
            status = "metadata_belum_lengkap"
        elif all(
            v is None
            for v in (harga, harga_mat, harga_jasa, total_mat, total_jasa, total)
        ):
            status = "perlu_review_tanpa_harga"

        items.append({
            "baris": row_num,
            "kode_item": clean_text(get_value("kode")) if get_value("kode") is not None else None,
            "nama_item": nama_str,
            "spesifikasi": clean_text(get_value("spesifikasi")) if get_value("spesifikasi") is not None else None,
            "qty": qty,
            "satuan": clean_text(satuan) if satuan is not None else None,
            "harga_satuan": harga,
            "harga_satuan_material": harga_mat,
            "harga_satuan_jasa": harga_jasa,
            "total_harga_material": total_mat,
            "total_harga_jasa": total_jasa,
            "total_harga": total,
            "bukti_sumber": source_cells,
            "status_validasi": status,
        })

    ringkasan = build_structured_ringkasan(summary_entries)

    return {
        "header_row": header_row,
        "column_mapping": mapping,
        "total_items": len(items),
        "items": items,
        "ringkasan_biaya": ringkasan,
        "audit": {
            "baris_terbaca": len(rows),
            "baris_item_diekstrak": len(items),
            "baris_ringkasan_diekstrak": len(summary_entries),
            "baris_dilewati": len(skipped),
            "detail_baris_dilewati": skipped,
        },
    }


# =========================================================
# REKONSILIASI NILAI UANG LINTAS ITEM & RINGKASAN
# =========================================================

def compute_financial_reconciliation(sheets_data: dict) -> dict:
    """
    Rekonsiliasi presisi penuh (tanpa pembulatan) antara penjumlahan item rincian
    dan nilai ringkasan yang tercatat di setiap sheet.
    """
    rekon = {}

    for title, sheet in sheets_data.items():
        items = sheet.get("items") or []
        ringkasan = sheet.get("ringkasan_biaya") or {}

        sum_mat = sum((it.get("total_harga_material") or 0.0) for it in items)
        sum_jasa = sum((it.get("total_harga_jasa") or 0.0) for it in items)
        sum_total = sum((it.get("total_harga") or 0.0) for it in items)

        sub_mat_sheet = ringkasan.get("total_sub_jumlah_material")
        sub_jasa_sheet = ringkasan.get("total_sub_jumlah_jasa")
        sub_total_sheet = ringkasan.get("total_sub_jumlah")

        rekon[title] = {
            "jumlah_item": len(items),
            "hasil_jumlah_item_material": sum_mat,
            "hasil_jumlah_item_jasa": sum_jasa,
            "hasil_jumlah_item_total": sum_total,
            "tercatat_total_sub_jumlah_material": sub_mat_sheet,
            "tercatat_total_sub_jumlah_jasa": sub_jasa_sheet,
            "tercatat_total_sub_jumlah": sub_total_sheet,
            "selisih_material_vs_tercatat": (
                (sum_mat - sub_mat_sheet) if sub_mat_sheet is not None else None
            ),
            "selisih_jasa_vs_tercatat": (
                (sum_jasa - sub_jasa_sheet) if sub_jasa_sheet is not None else None
            ),
            "selisih_total_vs_tercatat": (
                (sum_total - sub_total_sheet) if sub_total_sheet is not None else None
            ),
            "keuntungan_dan_resiko": ringkasan.get("keuntungan_dan_resiko"),
            "total_sebelum_pembulatan": ringkasan.get("total_sebelum_pembulatan"),
            "pembulatan": ringkasan.get("pembulatan"),
            "selisih_pembulatan": ringkasan.get("selisih_pembulatan"),
            "grand_total_akhir": ringkasan.get("grand_total_akhir"),
        }

    return rekon


# =========================================================
# FUNGSI UTAMA
# =========================================================

def extract_excel_bytes(
    file_bytes: bytes,
    filename: Optional[str] = None,
    doc_role: str = "vendor",
) -> dict:
    workbook = openpyxl.load_workbook(
        io.BytesIO(file_bytes),
        data_only=True,
        read_only=False,
    )

    try:
        if doc_role == "oe":
            vendor = {
                "nama": "OWNER ESTIMATE",
                "bukti_sumber": [],
                "status": "internal_oe",
            }
        else:
            vendor = detect_vendor(workbook)


        result = {
            "file_name": filename,
            "file_type": "xlsx",
            "vendor": vendor,
            "sheets": {},
            "rekonsiliasi_nilai": {},
            "audit": {
                "jumlah_sheet": len(workbook.worksheets),
                "sheet_diproses": 0,
                "sheet_tidak_dikenali": [],
            },
        }

        for ws in workbook.worksheets:
            if ws.sheet_state != "visible":
                continue

            rows, non_empty_count = read_sheet_rows(ws)
            if not rows:
                continue

            result["audit"]["sheet_diproses"] += 1
            extracted = extract_items_from_sheet(ws, rows)

            if extracted is None:
                result["audit"]["sheet_tidak_dikenali"].append(ws.title)
                result["sheets"][ws.title] = {
                    "status": "header_tidak_ditemukan",
                    "total_items": 0,
                    "items": [],
                    "audit": {
                        "baris_terbaca": non_empty_count,
                    },
                }
                continue

            extracted["audit"]["baris_non_kosong_di_worksheet"] = non_empty_count
            result["sheets"][ws.title] = extracted

        result["rekonsiliasi_nilai"] = compute_financial_reconciliation(result["sheets"])
        return result

    finally:
        workbook.close()