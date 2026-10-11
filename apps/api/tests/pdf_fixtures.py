"""Generated synthetic PDFs only; never read local user files."""

import hashlib

import pymupdf


def pdf_bytes(pages=2, active=False, encrypted=False, attachment=False):
    with pymupdf.open() as doc:
        for i in range(pages):
            page = doc.new_page()
            page.insert_text((72, 72), f"Synthetic math fixture page {i + 1}: x^2 - 4 = 0")
        if active:
            doc.xref_set_key(doc[0].xref, "AA", "<< /O << /S /JavaScript /JS (synthetic) >> >>")
        if attachment:
            doc.embfile_add("synthetic.txt", b"synthetic fixture")
        return (
            doc.tobytes(
                encryption=pymupdf.PDF_ENCRYPT_AES_256,
                owner_pw="synthetic-owner",
                user_pw="synthetic-reader",
            )
            if encrypted
            else (doc.tobytes())
        )


def metadata_for(data, pages=2, **changes):
    result = dict(
        filename="synthetic.pdf",
        media_type="application/pdf",
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        page_count=pages,
        assessment_type="marked_test",
    )
    result.update(changes)
    return result
