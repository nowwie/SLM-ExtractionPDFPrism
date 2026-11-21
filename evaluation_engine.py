import re
from difflib import SequenceMatcher
from typing import Any, Optional


UNIT_MAP = {
    "m2": "m²", "m^2": "m²",
    "m3": "m³", "m^3": "m³",
    "m'": "m", "m1": "m",
    "ea": "unit", "bh": "unit", "buah": "unit", "pcs": "unit",
    "ls": "ls", "lumpsum": "ls", "lump sum": "ls",
}


def normalize_unit(unit: Optional[str]) -> str:
    if not unit:
        return ""
    u = str(unit).strip().lower()
    return UNIT_MAP.get(u, u)


def normalize_item_text(text: Optional[str]) -> str:
    if not text:
        return ""
    t = str(text).lower().replace(",", ".")
    t = re.sub(r"[^a-z0-9²³.\s/-]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def build_context_signature(item: dict) -> str:
    """Menggabungkan hierarki WBS + nama item agar item kembar beda area tidak tertukar."""
    h = item.get("hierarki") or {}
    parts = [
        h.get("bab") or "",
        h.get("sub_bab") or "",
        h.get("kelompok_pekerjaan") or "",
        item.get("nama_item") or "",
    ]
    return normalize_item_text(" | ".join(p for p in parts if p))


def similarity_score(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


# =========================================================
# EKSTRAKSI SHEET BOQ UTAMA & ADAPTER FORM A5
# =========================================================

def get_primary_boq_sheet(doc: dict) -> tuple[Optional[str], dict]:
    """Mengambil sheet rincian BOQ utama (mengabaikan sheet Rekapitulasi)."""
    unwrapped = doc.get("extraction") or doc.get("result") or doc
    sheets = unwrapped.get("sheets") or {}

    for title, data in sheets.items():
        if data.get("status") in {"sheet_rekapitulasi", "header_tidak_ditemukan"}:
            continue
        if data.get("items"):
            return title, data

    return None, {}


def _find_first_key(obj: Any, candidate_keys: tuple[str, ...]) -> Any:
    """Pencarian key rekursif untuk beradaptasi dengan skema JSON Form A5 LlamaExtract."""
    if isinstance(obj, dict):
        lower_map = {str(k).lower(): v for k, v in obj.items()}
        for key in candidate_keys:
            if key in lower_map and lower_map[key] is not None:
                return lower_map[key]
        for v in obj.values():
            found = _find_first_key(v, candidate_keys)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_first_key(item, candidate_keys)
            if found is not None:
                return found
    return None


def _parse_percentage(raw_val: Any) -> Optional[float]:
    if raw_val is None or isinstance(raw_val, bool):
        return None
    if isinstance(raw_val, (int, float)):
        val = float(raw_val)
    else:
        cleaned = re.sub(r"[^\d,.\-]", "", str(raw_val)).replace(",", ".")
        try:
            val = float(cleaned)
        except ValueError:
            return None
    # Jika tertulis dalam skala desimal (mis. 0.425), konversi ke persen (42.5)
    if 0 < val <= 1.0:
        return round(val * 100.0, 4)
    return val


def parse_form_a5_data(form_a5_doc: Optional[dict]) -> dict:
    """Menyeragamkan output JSON dari extract_form_a5_bytes."""
    if not form_a5_doc:
        return {
            "status": "tidak_dilampirkan",
            "nama_vendor": None,
            "tkdn_gabungan_persen": 0.0,
            "tkdn_material_persen": None,
            "tkdn_jasa_persen": None,
        }

    unwrapped = form_a5_doc.get("extraction") or form_a5_doc.get("result") or form_a5_doc

    vendor_name = _find_first_key(
        unwrapped,
        ("nama_vendor", "nama_perusahaan", "vendor", "penyedia", "nama_penyedia", "nama"),
    )
    tkdn_gabungan = _parse_percentage(
        _find_first_key(
            unwrapped,
            (
                "tkdn_gabungan_persen",
                "tkdn_gabungan",
                "tkdn_persen",
                "persentase_tkdn",
                "nilai_tkdn",
                "capaian_tkdn",
                "tkdn",
            ),
        )
    )
    tkdn_material = _parse_percentage(
        _find_first_key(unwrapped, ("tkdn_material_persen", "tkdn_material", "tkdn_barang"))
    )
    tkdn_jasa = _parse_percentage(
        _find_first_key(unwrapped, ("tkdn_jasa_persen", "tkdn_jasa"))
    )

    if tkdn_gabungan is None and tkdn_material is not None and tkdn_jasa is not None:
        tkdn_gabungan = round((tkdn_material + tkdn_jasa) / 2.0, 4)

    return {
        "status": "terdeteksi" if tkdn_gabungan is not None else "tkdn_tidak_terbaca",
        "nama_vendor": str(vendor_name).strip() if vendor_name else None,
        "tkdn_gabungan_persen": tkdn_gabungan if tkdn_gabungan is not None else 0.0,
        "tkdn_material_persen": tkdn_material,
        "tkdn_jasa_persen": tkdn_jasa,
    }


# =========================================================
# 1. ITEM ALIGNMENT ENGINE (OE <-> VENDOR)
# =========================================================

def align_oe_with_vendor(oe_items: list[dict], vendor_items: list[dict]) -> dict:
    matched = []
    ambiguous = []
    used_vendor_idx = set()

    for oe in oe_items:
        oe_code = (oe.get("kode_item") or "").strip()
        oe_valid_code = oe_code not in {"", "-", "—"}
        oe_sig = build_context_signature(oe)
        oe_name = normalize_item_text(oe.get("nama_item"))
        oe_unit = normalize_unit(oe.get("satuan"))

        best_idx = None
        best_score = 0.0
        match_method = None

        for idx, v in enumerate(vendor_items):
            if idx in used_vendor_idx:
                continue

            v_code = (v.get("kode_item") or "").strip()
            v_sig = build_context_signature(v)
            v_name = normalize_item_text(v.get("nama_item"))
            v_unit = normalize_unit(v.get("satuan"))

            # Tier 1: Kode item valid identik + nama item mirip
            if oe_valid_code and oe_code == v_code:
                name_sim = similarity_score(oe_name, v_name)
                if name_sim >= 0.80:
                    best_idx = idx
                    best_score = 1.0
                    match_method = "exact_code_and_name"
                    break

            # Tier 2: Kemiripan konteks hierarki WBS (40%) + nama item (60%)
            ctx_sim = similarity_score(oe_sig, v_sig)
            name_sim = similarity_score(oe_name, v_name)
            combined = (0.4 * ctx_sim) + (0.6 * name_sim)

            if oe_unit and v_unit and oe_unit != v_unit:
                combined -= 0.08

            if combined > best_score:
                best_score = combined
                best_idx = idx
                match_method = "contextual_similarity"

        if best_idx is not None and best_score >= 0.88:
            used_vendor_idx.add(best_idx)
            matched.append({
                "status": "matched",
                "method": match_method,
                "confidence": round(best_score, 4),
                "oe_item": oe,
                "vendor_item": vendor_items[best_idx],
            })
        elif best_idx is not None and best_score >= 0.65:
            used_vendor_idx.add(best_idx)
            ambiguous.append({
                "status": "needs_llm_review",
                "confidence": round(best_score, 4),
                "oe_item": oe,
                "vendor_item": vendor_items[best_idx],
            })
        else:
            matched.append({
                "status": "unmatched_oe",
                "confidence": round(best_score, 4),
                "oe_item": oe,
                "vendor_item": None,
            })

    extra_vendor = [
        v for idx, v in enumerate(vendor_items) if idx not in used_vendor_idx
    ]

    return {
        "total_oe": len(oe_items),
        "total_vendor": len(vendor_items),
        "auto_matched": sum(1 for m in matched if m["status"] == "matched"),
        "needs_llm_review": len(ambiguous),
        "unmatched_oe": sum(1 for m in matched if m["status"] == "unmatched_oe"),
        "extra_vendor_items": len(extra_vendor),
        "aligned_items": matched,
        "ambiguous_items": ambiguous,
        "extra_vendor": extra_vendor,
    }


# =========================================================
# 2. KOREKSI ARITMATIKA, DETEKSI HARGA TIMPANG & PARETO
# =========================================================

def _compute_corrected_subtotal(items: list[dict]) -> tuple[float, float, float, int]:
    """Menghitung ulang total material, jasa, dan jumlah koreksi aritmatika item."""
    sum_mat = 0.0
    sum_jasa = 0.0
    arithmetic_fixes = 0

    for it in items:
        qty = it.get("qty")
        h_mat = it.get("harga_satuan_material")
        h_jasa = it.get("harga_satuan_jasa")
        h_unit = it.get("harga_satuan")

        rec_mat = it.get("total_harga_material") or 0.0
        rec_jasa = it.get("total_harga_jasa") or 0.0

        if qty is not None and (h_mat is not None or h_jasa is not None):
            calc_mat = qty * (h_mat or 0.0)
            calc_jasa = qty * (h_jasa or 0.0)
            if abs((calc_mat + calc_jasa) - (rec_mat + rec_jasa)) > 1.0:
                arithmetic_fixes += 1
            sum_mat += calc_mat
            sum_jasa += calc_jasa
        elif qty is not None and h_unit is not None:
            calc_tot = qty * h_unit
            rec_tot = it.get("total_harga") or 0.0
            if abs(calc_tot - rec_tot) > 1.0:
                arithmetic_fixes += 1
            sum_mat += calc_tot
        else:
            sum_mat += rec_mat
            sum_jasa += rec_jasa

    return sum_mat, sum_jasa, (sum_mat + sum_jasa), arithmetic_fixes


def evaluate_single_vendor(
    oe_doc: dict,
    vendor_doc: dict,
    form_a5_doc: Optional[dict] = None,
    threshold_timpang_persen: float = 110.0,
    mode_preferensi: str = "tunggal",  # "tunggal" atau "terpisah_material_jasa"
    preferensi_maks_persen: float = 7.5,
    preferensi_material_maks_persen: float = 25.0,
    preferensi_jasa_maks_persen: float = 7.5,
) -> dict:
    """Mengevaluasi 1 vendor terhadap OE dan menghitung nilai HEA-nya."""
    oe_unwrapped = oe_doc.get("extraction") or oe_doc.get("result") or oe_doc
    v_unwrapped = vendor_doc.get("extraction") or vendor_doc.get("result") or vendor_doc

    _, oe_sheet = get_primary_boq_sheet(oe_unwrapped)
    _, v_sheet = get_primary_boq_sheet(v_unwrapped)

    oe_items = oe_sheet.get("items") or []
    v_items = v_sheet.get("items") or []

    # Hitung pagu total OE
    oe_ringkasan = oe_sheet.get("ringkasan_biaya") or {}
    oe_mat, oe_jasa, oe_sub, _ = _compute_corrected_subtotal(oe_items)
    oe_kr = oe_ringkasan.get("keuntungan_dan_resiko") or 0.0
    oe_total_pagu = oe_ringkasan.get("grand_total_akhir") or (oe_sub + oe_kr)

    # Alignment item OE <-> Vendor
    alignment = align_oe_with_vendor(oe_items, v_items)

    # Koreksi aritmatika penawaran vendor
    v_ringkasan = v_sheet.get("ringkasan_biaya") or {}
    v_mat, v_jasa, v_sub_terkoreksi, jumlah_koreksi_aritmatika = _compute_corrected_subtotal(v_items)

    sub_tercatat = v_ringkasan.get("total_sub_jumlah")
    kr_tercatat = v_ringkasan.get("keuntungan_dan_resiko") or 0.0
    if sub_tercatat and sub_tercatat > 0 and kr_tercatat > 0:
        kr_terkoreksi = v_sub_terkoreksi * (kr_tercatat / sub_tercatat)
    else:
        kr_terkoreksi = kr_tercatat

    harga_penawaran_terkoreksi = v_sub_terkoreksi + kr_terkoreksi

    # Audit harga timpang & selisih per item
    item_comparisons = []
    jumlah_timpang = 0
    jumlah_deviasi_qty = 0

    for pair in alignment["aligned_items"] + alignment["ambiguous_items"]:
        oe_it = pair["oe_item"]
        v_it = pair.get("vendor_item")
        if v_it is None:
            continue

        oe_unit_price = (
            (oe_it.get("harga_satuan_material") or 0.0)
            + (oe_it.get("harga_satuan_jasa") or 0.0)
            or (oe_it.get("harga_satuan") or 0.0)
        )
        v_unit_price = (
            (v_it.get("harga_satuan_material") or 0.0)
            + (v_it.get("harga_satuan_jasa") or 0.0)
            or (v_it.get("harga_satuan") or 0.0)
        )

        oe_tot = oe_it.get("total_harga") or 0.0
        v_tot = v_it.get("total_harga") or 0.0
        selisih_nominal = v_tot - oe_tot

        if oe_unit_price > 0:
            rasio_persen = round((v_unit_price / oe_unit_price) * 100.0, 2)
            is_timpang = rasio_persen > threshold_timpang_persen
        else:
            rasio_persen = None
            is_timpang = False

        if is_timpang:
            jumlah_timpang += 1

        qty_beda = (
            oe_it.get("qty") is not None
            and v_it.get("qty") is not None
            and abs(oe_it["qty"] - v_it["qty"]) > 1e-6
        )
        if qty_beda:
            jumlah_deviasi_qty += 1

        item_comparisons.append({
            "kode_item": v_it.get("kode_item") or oe_it.get("kode_item"),
            "nama_item": v_it.get("nama_item"),
            "bab": (v_it.get("hierarki") or {}).get("bab"),
            "match_status": pair["status"],
            "match_confidence": pair["confidence"],
            "qty_oe": oe_it.get("qty"),
            "qty_vendor": v_it.get("qty"),
            "deviasi_qty": qty_beda,
            "harga_satuan_oe": oe_unit_price,
            "harga_satuan_vendor": v_unit_price,
            "rasio_harga_satuan_persen": rasio_persen,
            "is_harga_timpang": is_timpang,
            "total_oe": oe_tot,
            "total_vendor": v_tot,
            "selisih_total_nominal": selisih_nominal,
        })

    # Top 10 target negosiasi (item di atas OE dengan selisih nominal terbesar)
    target_negosiasi = sorted(
        [x for x in item_comparisons if x["selisih_total_nominal"] > 0],
        key=lambda x: x["selisih_total_nominal"],
        reverse=True,
    )[:10]

    # Kalkulasi HEA berdasarkan TKDN Form A5
    a5_info = parse_form_a5_data(form_a5_doc)
    tkdn_pct = a5_info["tkdn_gabungan_persen"]

    if mode_preferensi == "terpisah_material_jasa":
        tkdn_mat = (
            a5_info["tkdn_material_persen"]
            if a5_info["tkdn_material_persen"] is not None
            else tkdn_pct
        )
        tkdn_jasa = (
            a5_info["tkdn_jasa_persen"]
            if a5_info["tkdn_jasa_persen"] is not None
            else tkdn_pct
        )
        kp_mat = (tkdn_mat / 100.0) * (preferensi_material_maks_persen / 100.0)
        kp_jasa = (tkdn_jasa / 100.0) * (preferensi_jasa_maks_persen / 100.0)
        hea = (v_mat / (1.0 + kp_mat)) + (v_jasa / (1.0 + kp_jasa)) + kr_terkoreksi
        kp_efektif = (harga_penawaran_terkoreksi / hea) - 1.0 if hea > 0 else 0.0
    else:
        kp_efektif = (tkdn_pct / 100.0) * (preferensi_maks_persen / 100.0)
        hea = harga_penawaran_terkoreksi / (1.0 + kp_efektif)

    selisih_vs_oe = harga_penawaran_terkoreksi - oe_total_pagu
    selisih_vs_oe_persen = (
        round((selisih_vs_oe / oe_total_pagu) * 100.0, 2) if oe_total_pagu > 0 else None
    )

    vendor_nama = (
        (v_unwrapped.get("vendor") or {}).get("nama")
        or a5_info.get("nama_vendor")
        or v_unwrapped.get("file_name")
        or "Vendor Tanpa Nama"
    )

    return {
        "vendor_nama": vendor_nama,
        "file_penawaran": v_unwrapped.get("file_name"),
        "ringkasan_finansial": {
            "pagu_oe": oe_total_pagu,
            "penawaran_tercatat_akhir": v_ringkasan.get("grand_total_akhir"),
            "subtotal_material_terkoreksi": v_mat,
            "subtotal_jasa_terkoreksi": v_jasa,
            "keuntungan_dan_resiko_terkoreksi": kr_terkoreksi,
            "harga_penawaran_terkoreksi": harga_penawaran_terkoreksi,
            "selisih_terhadap_oe": selisih_vs_oe,
            "selisih_terhadap_oe_persen": selisih_vs_oe_persen,
            "status_pagu_oe": "di_atas_oe" if selisih_vs_oe > 0 else "di_bawah_atau_sama_oe",
        },
        "tkdn_dan_hea": {
            "status_form_a5": a5_info["status"],
            "tkdn_persen": tkdn_pct,
            "mode_preferensi": mode_preferensi,
            "koefisien_preferensi_persen": round(kp_efektif * 100.0, 4),
            "nilai_hea": hea,
        },
        "kualitas_penawaran": {
            "item_matched": alignment["auto_matched"],
            "item_perlu_review_llm": alignment["needs_llm_review"],
            "item_oe_tidak_ada": alignment["unmatched_oe"],
            "item_tambahan_vendor": alignment["extra_vendor_items"],
            "jumlah_koreksi_aritmatika": jumlah_koreksi_aritmatika,
            "jumlah_harga_timpang": jumlah_timpang,
            "jumlah_deviasi_qty": jumlah_deviasi_qty,
        },
        "top_target_negosiasi": target_negosiasi,
        "detail_komparasi_item": item_comparisons,
        "item_ambigu_perlu_llm": alignment["ambiguous_items"],
    }


# =========================================================
# 3. MODUL PERANGKINGAN MULTI-VENDOR
# =========================================================

def rank_vendors(
    oe_doc: dict,
    vendor_submissions: list[dict],
    threshold_timpang_persen: float = 110.0,
    mode_preferensi: str = "tunggal",
    preferensi_maks_persen: float = 7.5,
    preferensi_material_maks_persen: float = 25.0,
    preferensi_jasa_maks_persen: float = 7.5,
) -> dict:
    """
    Mengevaluasi dan mengurutkan banyak vendor berdasarkan nilai HEA terendah.
    Setiap elemen pada `vendor_submissions` berbentuk:
      {"penawaran": <hasil_extract_excel>, "form_a5": <hasil_extract_form_a5_atau_None>}
    """
    evaluations = []
    for sub in vendor_submissions:
        ev = evaluate_single_vendor(
            oe_doc=oe_doc,
            vendor_doc=sub["penawaran"],
            form_a5_doc=sub.get("form_a5"),
            threshold_timpang_persen=threshold_timpang_persen,
            mode_preferensi=mode_preferensi,
            preferensi_maks_persen=preferensi_maks_persen,
            preferensi_material_maks_persen=preferensi_material_maks_persen,
            preferensi_jasa_maks_persen=preferensi_jasa_maks_persen,
        )
        evaluations.append(ev)

    # Urutkan berdasarkan HEA terendah (peringkat 1 = pemenang sementara)
    evaluations.sort(key=lambda x: x["tkdn_dan_hea"]["nilai_hea"])

    best_hea = evaluations[0]["tkdn_dan_hea"]["nilai_hea"] if evaluations else 0.0
    tabel_peringkat = []

    for idx, ev in enumerate(evaluations, start=1):
        fin = ev["ringkasan_finansial"]
        hea_info = ev["tkdn_dan_hea"]
        qual = ev["kualitas_penawaran"]
        selisih_hea_p1 = hea_info["nilai_hea"] - best_hea

        tabel_peringkat.append({
            "peringkat": idx,
            "vendor_nama": ev["vendor_nama"],
            "file_penawaran": ev["file_penawaran"],
            "harga_penawaran_terkoreksi": fin["harga_penawaran_terkoreksi"],
            "selisih_vs_oe_persen": fin["selisih_terhadap_oe_persen"],
            "status_pagu_oe": fin["status_pagu_oe"],
            "tkdn_persen": hea_info["tkdn_persen"],
            "koefisien_preferensi_persen": hea_info["koefisien_preferensi_persen"],
            "nilai_hea": hea_info["nilai_hea"],
            "selisih_hea_dari_peringkat_1": selisih_hea_p1,
            "jumlah_harga_timpang": qual["jumlah_harga_timpang"],
            "item_oe_tidak_ada": qual["item_oe_tidak_ada"],
            "item_perlu_review_llm": qual["item_perlu_review_llm"],
        })

    return {
        "total_vendor_dievaluasi": len(tabel_peringkat),
        "pemenang_sementara": tabel_peringkat[0] if tabel_peringkat else None,
        "tabel_peringkat": tabel_peringkat,
        "detail_evaluasi_per_vendor": evaluations,
    }