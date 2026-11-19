from llama_extract import process_form_a5_pdf


def extract_form_a5_bytes(file_bytes: bytes) -> dict:
    return process_form_a5_pdf(file_bytes)
