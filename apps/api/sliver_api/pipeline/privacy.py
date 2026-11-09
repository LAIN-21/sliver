"""Stage 3: personal-data scan. Findings cite columns, counts and row numbers, never the values."""

import re
from collections.abc import Callable
from dataclasses import dataclass

from .context import StageContext
from .table import MAX_EXAMPLE_ROWS, StageResult, count, finding


def luhn_valid(digits: str) -> bool:
    total = 0
    for position, char in enumerate(reversed(digits)):
        value = int(char)
        if position % 2:
            value = value * 2 - 9 if value > 4 else value * 2
        total += value
    return total % 10 == 0


def iban_valid(candidate: str) -> bool:
    compact = candidate.replace(" ", "").upper()
    if not 15 <= len(compact) <= 34:
        return False
    rearranged = compact[4:] + compact[:4]
    return int("".join(str(int(char, 36)) for char in rearranged)) % 97 == 1


def digits_only(text: str) -> str:
    return re.sub(r"\D", "", text)


@dataclass(frozen=True)
class Detector:
    code: str
    label: str
    severity: str
    pattern: re.Pattern
    check: Callable[[str], bool] = lambda _match: True
    # Cheap pre-filter so most cells skip the regular expression entirely.
    hint: Callable[[str], bool] = lambda _cell: True


DETECTORS = (
    Detector(
        "email",
        "email addresses",
        "medium",
        re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"),
        hint=lambda cell: "@" in cell,
    ),
    Detector(
        "card_number",
        "payment card numbers (Luhn-valid)",
        "high",
        re.compile(r"(?<![\d.-])[2-6](?:[ -]?\d){12,18}(?![\d.-])"),
        check=lambda match: 13 <= len(digits_only(match)) <= 19 and luhn_valid(digits_only(match)),
        hint=lambda cell: sum(char.isdigit() for char in cell) >= 13,
    ),
    Detector(
        "iban",
        "IBANs (checksum-valid)",
        "high",
        re.compile(r"(?<![A-Za-z0-9])[A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,30}(?![A-Za-z0-9])"),
        check=iban_valid,
        hint=lambda cell: len(cell) >= 15,
    ),
    Detector(
        "nric_fin",
        "Singapore NRIC/FIN numbers",
        "high",
        re.compile(r"(?<![A-Za-z0-9])[STFGM]\d{7}[A-Z](?![A-Za-z0-9])"),
        hint=lambda cell: len(cell) >= 9,
    ),
    Detector(
        "phone",
        "phone numbers",
        "medium",
        re.compile(
            # International (+65 6123 4567, +44 20 7946 0958), Singapore local (9123 4567) and
            # North American (555-123-4567) formats; bare digit runs are left alone.
            r"(?<![\w+])\+\d{1,3}(?:[ .-]?\(?\d{1,4}\)?){2,5}(?![\w])"
            r"|(?<![\w.-])[689]\d{3}[ -]\d{4}(?![\w.-])"
            r"|(?<![\w.-])\(?\d{3}\)?[ -]\d{3}-\d{4}(?![\w.-])"
        ),
        check=lambda match: 8 <= len(digits_only(match)) <= 15,
        hint=lambda cell: sum(char.isdigit() for char in cell) >= 8,
    ),
)

# Column names that suggest personal data even when no value matched a detector. A name matches
# when it equals an entry or ends with one ("customer_email", "holderPassportNumber").
IDENTIFIER_NAMES = {
    "nric", "nric_fin", "passport", "passport_number", "passport_no", "ssn", "social_security_number",
    "national_id", "credit_card", "card_number", "cvv", "iban", "account_number", "bank_account",
    "tax_id", "password", "diagnosis", "medical_condition",
}  # fmt: skip
PERSONAL_NAMES = {
    "email", "e_mail", "email_address", "phone", "phone_number", "mobile", "mobile_number", "telephone",
    "first_name", "last_name", "full_name", "surname", "given_name", "dob", "date_of_birth", "birth_date",
    "birthday", "address", "postcode", "postal_code", "zip_code", "salary", "income", "gender",
    "ethnicity", "religion", "ip_address",
}  # fmt: skip
# Too generic to match as a suffix ("vessel_name", "port_zip"); flagged only as the whole name.
EXACT_ONLY = {"fin": "medium", "name": "low", "zip": "low", "tel": "low", "ip": "low"}
PERSON_WORDS = {"customer", "contact", "person", "client", "patient", "employee", "user", "holder", "driver"}


def name_tokens(name: str) -> list[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name.strip())
    return [token for token in re.split(r"[^a-z0-9]+", spaced.lower()) if token]


def sensitive_name(name: str) -> str | None:
    tokens = name_tokens(name)
    if not tokens:
        return None
    joined = "_".join(tokens)
    suffixes = {"_".join(tokens[start:]) for start in range(len(tokens))}
    if suffixes & IDENTIFIER_NAMES:
        return "medium"
    if joined in EXACT_ONLY:
        return EXACT_ONLY[joined]
    if suffixes & PERSONAL_NAMES:
        return "low"
    if tokens[-1] == "name" and PERSON_WORDS & set(tokens):
        return "low"
    return None


def scan_column(values: list[str]) -> dict[str, list[int]]:
    hits: dict[str, list[int]] = {}
    for row_number, cell in enumerate(values, start=1):
        if not cell or len(cell) < 6:
            continue
        for detector in DETECTORS:
            if not detector.hint(cell):
                continue
            if any(detector.check(match.group(0)) for match in detector.pattern.finditer(cell)):
                hits.setdefault(detector.code, []).append(row_number)
    return hits


def run(context: StageContext) -> StageResult:
    table = context.table
    by_code = {detector.code: detector for detector in DETECTORS}
    findings = []
    flagged_columns = set()
    for index, name in enumerate(table.header):
        for code, rows in scan_column(table.column(index)).items():
            detector = by_code[code]
            flagged_columns.add(name)
            shown = ", ".join(str(row) for row in rows[:MAX_EXAMPLE_ROWS]) + (", …" if len(rows) > 5 else "")
            findings.append(
                finding(
                    code,
                    detector.severity,
                    f"{count(len(rows), 'value')} in “{name}” resembling {detector.label} (rows {shown}).",
                    column=name,
                    rows=rows[:MAX_EXAMPLE_ROWS],
                    count=len(rows),
                )
            )
        severity = sensitive_name(name)
        if severity:
            findings.append(
                finding(
                    "sensitive_column_name",
                    severity,
                    f"Column name “{name}” suggests personal data.",
                    column=name,
                )
            )
    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda item: order[item["severity"]])
    if not findings:
        summary = "No personal data detected."
    else:
        columns = count(len(flagged_columns), "column")
        summary = f"Possible personal data in {columns}; {count(len(findings), 'finding')}."
    return StageResult(
        summary=summary, findings=findings, details={"scanned_cells": len(table.rows) * len(table.header)}
    )
