"""Resource-bounded subprocess. Never emits parser errors, paths or PDF text."""

import json
import re
import resource
import sys


def main() -> None:
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    import pymupdf

    from app.limits import MAX_DOCUMENT_PAGES, MAX_UPLOAD_BYTES

    pymupdf.TOOLS.mupdf_display_errors(False)  # type: ignore[no-untyped-call]
    pymupdf.TOOLS.mupdf_display_warnings(False)  # type: ignore[no-untyped-call]
    data = sys.stdin.buffer.read(MAX_UPLOAD_BYTES + 1)
    result: dict[str, object] = {"error": "invalid_document"}
    try:
        with pymupdf.open(stream=data, filetype="pdf") as doc:  # type: ignore[no-untyped-call]
            if doc.needs_pass or doc.is_encrypted:
                result = {"error": "encrypted_document"}
            elif not doc.is_pdf or doc.is_repaired:
                pass
            elif not 1 <= doc.page_count <= MAX_DOCUMENT_PAGES:
                result = {"error": "page_limit"}
            elif doc.embfile_count() or doc.xref_length() > 100000:
                result = {"error": "unsupported_pdf_features"}
            else:
                blocked = {
                    "AA",
                    "OpenAction",
                    "JS",
                    "JavaScript",
                    "EmbeddedFiles",
                    "EF",
                    "RichMediaContent",
                    "XFA",
                }
                active = False
                syntax_bytes = 0
                for xref in range(1, doc.xref_length()):
                    syntax = doc.xref_object(xref)
                    syntax_bytes += len(syntax)
                    if syntax_bytes > 16 * 1024 * 1024 or re.search(
                        r"/(?:AA|OpenAction|JS|JavaScript|Launch|EmbeddedFiles?|EF|XFA|"
                        r"RichMediaContent|GoToR|SubmitForm|ImportData|Rendition)(?:[^A-Za-z]|$)",
                        syntax,
                    ):
                        active = True
                        break
                    keys = set(doc.xref_get_keys(xref))
                    if keys & blocked:
                        active = True
                        break
                    if "S" in keys:
                        _, action = doc.xref_get_key(xref, "S")
                        if action in {
                            "/JavaScript",
                            "/Launch",
                            "/GoToR",
                            "/SubmitForm",
                            "/ImportData",
                            "/Rendition",
                        }:
                            active = True
                            break
                if active:
                    result = {"error": "unsupported_pdf_features"}
                else:
                    result = {"page_count": doc.page_count}
    except Exception:
        pass
    print(json.dumps(result))


if __name__ == "__main__":
    main()
