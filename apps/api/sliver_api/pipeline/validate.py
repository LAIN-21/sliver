"""Stage 1: bounded, deterministic file-quality checks. These do not verify ownership."""

import csv
import io

from .context import StageContext
from .table import (
    MAX_COLUMNS,
    MAX_EXAMPLE_ROWS,
    MAX_FIELD_CHARS,
    MAX_FILE_BYTES,
    MAX_HEADER_CHARS,
    MAX_ROWS,
    StageResult,
    count,
    finding,
    looks_like_formula,
)


def fail(code: str, message: str) -> StageResult:
    return StageResult(summary=message, findings=[finding(code, "high", message)])


def rows_text(rows: list[int]) -> str:
    shown = ", ".join(str(row) for row in rows[:MAX_EXAMPLE_ROWS])
    return shown + (", …" if len(rows) > MAX_EXAMPLE_ROWS else "")


def inspect_csv(data: bytes) -> StageResult:
    if not data:
        return fail("empty_file", "The file is empty.")
    if len(data) > MAX_FILE_BYTES:
        return fail("file_size", "CSV files may be at most 5 MiB.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        return fail(
            "encoding", f"The file is not UTF-8 (invalid byte at offset {error.start}). Save it as UTF-8."
        )
    if "\0" in text:
        return fail("null_byte", "The file contains NUL bytes; it does not look like a text CSV.")

    findings: list[dict] = []
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        header = next(reader, [])
        if not header or header == [""]:
            return fail("no_header", "The first line must be a header row with column names.")
        if len(header) > MAX_COLUMNS:
            return fail("columns", f"CSV has {len(header)} columns; the limit is {MAX_COLUMNS}.")
        for index, name in enumerate(header, start=1):
            label = name.strip() or f"column {index}"
            if not name.strip():
                findings.append(finding("empty_header", "high", f"Column {index} has no name.", column=label))
            elif len(name) > MAX_HEADER_CHARS:
                findings.append(
                    finding(
                        "long_header", "high", f"Column {index} name exceeds 160 characters.", column=label
                    )
                )
            if looks_like_formula(name):
                findings.append(
                    finding(
                        "spreadsheet_formula_header",
                        "high",
                        f"Column name “{label[:60]}” would run as a spreadsheet formula. Rename it.",
                        column=label,
                    )
                )
        seen_names: dict[str, int] = {}
        for index, name in enumerate(header, start=1):
            key = name.strip().casefold()
            if key and key in seen_names:
                findings.append(
                    finding(
                        "duplicate_header",
                        "high",
                        f"Columns {seen_names[key]} and {index} have the same name “{name.strip()[:60]}”.",
                        column=name.strip(),
                    )
                )
            seen_names.setdefault(key, index)

        row_count = 0
        width_rows: list[int] = []
        long_rows: list[int] = []
        missing_cells = 0
        missing_columns: set[int] = set()
        formula_cells: dict[int, list[int]] = {}
        duplicate_rows: list[int] = []
        seen_rows: set[tuple[str, ...]] = set()
        for row in reader:
            row_count += 1
            if row_count > MAX_ROWS:
                return fail("rows", f"CSV has more than {MAX_ROWS:,} data rows.")
            if len(row) != len(header):
                width_rows.append(row_count)
                continue
            if any(len(value) > MAX_FIELD_CHARS for value in row):
                long_rows.append(row_count)
            for index, value in enumerate(row):
                if not value.strip():
                    missing_cells += 1
                    missing_columns.add(index)
                elif looks_like_formula(value):
                    formula_cells.setdefault(index, []).append(row_count)
            key = tuple(row)
            if key in seen_rows:
                duplicate_rows.append(row_count)
            seen_rows.add(key)
    except csv.Error as error:
        return fail("syntax", f"CSV syntax is invalid near data row {reader.line_num - 1}: {error}.")

    if row_count == 0:
        findings.append(finding("no_rows", "high", "The CSV has a header but no data rows."))
    if width_rows:
        findings.append(
            finding(
                "row_width",
                "high",
                f"{count(len(width_rows), 'data row')} with the wrong number of fields "
                f"(expected {len(header)}; rows {rows_text(width_rows)}).",
                rows=width_rows[:MAX_EXAMPLE_ROWS],
                count=len(width_rows),
            )
        )
    if long_rows:
        findings.append(
            finding(
                "field_size",
                "high",
                f"{count(len(long_rows), 'row')} with a field longer than {MAX_FIELD_CHARS:,} characters "
                f"(rows {rows_text(long_rows)}).",
                rows=long_rows[:MAX_EXAMPLE_ROWS],
                count=len(long_rows),
            )
        )
    for index, rows in formula_cells.items():
        findings.append(
            finding(
                "spreadsheet_formula",
                "medium",
                f"{count(len(rows), 'cell')} starting with =, +, - or @ that spreadsheets run as formulas "
                f"(rows {rows_text(rows)}).",
                column=header[index],
                rows=rows[:MAX_EXAMPLE_ROWS],
                count=len(rows),
            )
        )
    if missing_cells:
        names = ", ".join(header[index] for index in sorted(missing_columns)[:10])
        findings.append(
            finding(
                "missing_values",
                "low",
                f"{count(missing_cells, 'empty cell')} (columns: {names}).",
                count=missing_cells,
            )
        )
    if duplicate_rows:
        findings.append(
            finding(
                "duplicate_rows",
                "low",
                f"{count(len(duplicate_rows), 'row')} repeating an earlier row exactly "
                f"(rows {rows_text(duplicate_rows)}).",
                rows=duplicate_rows[:MAX_EXAMPLE_ROWS],
                count=len(duplicate_rows),
            )
        )

    result = StageResult(
        summary="",
        findings=findings,
        details={"columns": len(header), "rows": row_count},
        dataset_updates={"row_count": row_count},
    )
    if result.status == "failed":
        blocking = sum(1 for item in findings if item["severity"] == "high")
        result.summary = f"Invalid CSV: {blocking} blocking issue{'s' if blocking != 1 else ''}."
    else:
        result.summary = f"Valid UTF-8 CSV with {len(header)} columns and {row_count:,} rows."
    return result


def run(context: StageContext) -> StageResult:
    return inspect_csv(context.data)
