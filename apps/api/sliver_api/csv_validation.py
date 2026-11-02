"""Bounded, deterministic file-quality checks; these do not verify ownership."""

import csv
import io

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ROWS = 10_000
MAX_COLUMNS = 100
MAX_FIELD_CHARS = 10_000


class InvalidCSV(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.issue = {"code": code, "message": message}


def inspect_csv(data: bytes) -> dict:
    if not data or len(data) > MAX_FILE_BYTES:
        raise InvalidCSV("file_size", "CSV must contain between 1 byte and 5 MiB.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise InvalidCSV("encoding", "Upload a UTF-8 encoded CSV.") from None
    if "\0" in text:
        raise InvalidCSV("null_byte", "CSV must not contain NUL bytes.")
    try:
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        columns = next(reader, [])
        if not columns or len(columns) > MAX_COLUMNS:
            raise InvalidCSV("columns", "CSV requires between 1 and 100 columns.")
        if any(not name.strip() or len(name) > 160 for name in columns):
            raise InvalidCSV("headers", "Column names must be nonempty and at most 160 characters.")
        if len({name.strip().casefold() for name in columns}) != len(columns):
            raise InvalidCSV("duplicate_headers", "Column names must be unique, ignoring case and outer spaces.")
        rows, preview, seen = 0, [], set()
        missing, duplicates, formulas = False, False, False
        for row in reader:
            rows += 1
            if rows > MAX_ROWS:
                raise InvalidCSV("rows", "CSV may contain at most 10,000 data rows.")
            if len(row) != len(columns):
                raise InvalidCSV("row_width", f"Data row {rows} has a different column count from the header.")
            if any(len(value) > MAX_FIELD_CHARS for value in row):
                raise InvalidCSV("field_size", f"Data row {rows} contains a field longer than 10,000 characters.")
            missing = missing or any(not value.strip() for value in row)
            formulas = formulas or any(value.lstrip().startswith(("=", "+", "-", "@")) for value in row)
            key = tuple(row)
            duplicates = duplicates or key in seen
            seen.add(key)
            if len(preview) < 20:
                preview.append(row)
        if rows == 0:
            raise InvalidCSV("empty", "CSV requires at least one data row.")
    except csv.Error:
        raise InvalidCSV("syntax", "CSV syntax is invalid or contains an excessively large field.") from None
    warnings = []
    if missing:
        warnings.append({"code": "missing_values", "message": "Some cells are empty; review coverage before publishing."})
    if duplicates:
        warnings.append({"code": "duplicate_rows", "message": "Duplicate rows were found; row count includes duplicates."})
    if formulas:
        warnings.append({"code": "spreadsheet_formula", "message": "Some cells may execute as spreadsheet formulas. Preview is text only; handle downloads carefully."})
    return {"columns": columns, "row_count": rows, "warnings": warnings, "preview": preview}
