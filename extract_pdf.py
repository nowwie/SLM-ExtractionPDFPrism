from pypdf import PdfReader
import json
import os

FILES = [
    "data/FORM A5 Komitmen TKDN PT Cakar Langit.pdf",
    "data/Form A5 Komitmen TKDN UJE.pdf"
]

all_results = {}

for file in FILES:
    print(f"Membaca: {file}")

    reader = PdfReader(file)
    pages = []

    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text()

        pages.append({
            "page": page_number,
            "text": text
        })

    file_name = os.path.basename(file)

    all_results[file_name] = {
        "total_pages": len(reader.pages),
        "pages": pages
    }

output_file = "data/extracted_pdf.json"

with open(output_file, "w", encoding="utf-8") as f:
    json.dump(
        all_results,
        f,
        ensure_ascii=False,
        indent=2
    )

print()
print("Selesai.")
print(f"Hasil disimpan ke: {output_file}")