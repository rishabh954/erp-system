from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from django.core.exceptions import ValidationError

MAX_DOCUMENT_FILE_SIZE = 10 * 1024 * 1024

_DOCUMENT_MIME_TYPES = {
    ".csv": "text/csv",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".json": "application/json",
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".rtf": "application/rtf",
    ".txt": "text/plain",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xml": "application/xml",
}
_OFFICE_ZIP_CONTENTS = {
    ".docx": "word/document.xml",
    ".pptx": "ppt/presentation.xml",
    ".xlsx": "xl/workbook.xml",
}
_OLE_SIGNATURE = bytes.fromhex("D0CF11E0A1B11AE1")
_PNG_SIGNATURE = bytes.fromhex("89504E470D0A1A0A")


def get_document_file_type(uploaded_file):
    if uploaded_file.size <= 0:
        raise ValidationError("The uploaded file is empty.")
    if uploaded_file.size > MAX_DOCUMENT_FILE_SIZE:
        raise ValidationError("Files must be 10 MB or smaller.")

    extension = Path(uploaded_file.name).suffix.lower()
    mime_type = _DOCUMENT_MIME_TYPES.get(extension)
    if not mime_type:
        raise ValidationError("This file type is not allowed.")

    uploaded_file.seek(0)
    try:
        content = uploaded_file.read()
    finally:
        uploaded_file.seek(0)

    valid = False
    if extension == ".pdf":
        valid = content.startswith(b"%PDF-")
    elif extension in {".jpg", ".jpeg"}:
        valid = content.startswith(b"\xff\xd8\xff")
    elif extension == ".png":
        valid = content.startswith(_PNG_SIGNATURE)
    elif extension == ".gif":
        valid = content.startswith((b"GIF87a", b"GIF89a"))
    elif extension in _OFFICE_ZIP_CONTENTS:
        try:
            with ZipFile(BytesIO(content)) as archive:
                valid = (
                    "[Content_Types].xml" in archive.namelist()
                    and _OFFICE_ZIP_CONTENTS[extension] in archive.namelist()
                )
        except BadZipFile:
            valid = False
    elif extension in {".doc", ".xls", ".ppt"}:
        valid = content.startswith(_OLE_SIGNATURE)
    elif extension == ".rtf":
        valid = content.startswith(b"{\\rtf")
    else:
        try:
            content.decode("utf-8-sig")
            valid = b"\x00" not in content
        except UnicodeDecodeError:
            valid = False

    if not valid:
        raise ValidationError(
            "The file contents do not match the selected file type."
        )
    return mime_type


def validate_document_file(uploaded_file):
    get_document_file_type(uploaded_file)
