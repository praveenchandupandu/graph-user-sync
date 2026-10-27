"""
transform.py - Converts a raw Microsoft Graph user into the target JSON format.

Graph field          ->  Target field
---------------------------------------
id                   ->  source_id
displayName          ->  full_name   (fallback: givenName + surname)
givenName            ->  first_name
surname              ->  last_name
mail                 ->  email       (fallback: userPrincipalName)
userPrincipalName    ->  username
jobTitle             ->  job_title
department           ->  department
officeLocation       ->  office
accountEnabled       ->  is_active

Missing-data rules:
  * No id                -> record cannot be tracked, so it is skipped (returned as None)
  * No mail              -> use userPrincipalName as email, log a warning
  * No displayName       -> build it from first + last name
  * Other missing fields -> stored as null, and listed in "missing_fields"
Empty strings / whitespace are treated the same as missing.
"""
import hashlib
import json


def _clean(value):
    """Strip whitespace; turn '' into None."""
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def transform_user(raw: dict) -> tuple[dict | None, list[str]]:
    """Returns (record, warnings). record is None if the user must be skipped."""
    warnings: list[str] = []

    source_id = _clean(raw.get("id"))
    if not source_id:
        return None, ["missing 'id' - record skipped"]

    first = _clean(raw.get("givenName"))
    last = _clean(raw.get("surname"))
    upn = _clean(raw.get("userPrincipalName"))
    mail = _clean(raw.get("mail"))

    full_name = _clean(raw.get("displayName"))
    if not full_name:
        full_name = " ".join(p for p in (first, last) if p) or None
        warnings.append("no displayName, built from first/last name" if full_name else "no name available")

    email = mail
    if not email:
        email = upn
        warnings.append("no mail, used userPrincipalName as email" if upn else "no mail and no userPrincipalName")

    record = {
        "source_id": source_id,
        "full_name": full_name,
        "first_name": first,
        "last_name": last,
        "email": email.lower() if email else None,
        "username": upn.lower() if upn else None,
        "job_title": _clean(raw.get("jobTitle")),
        "department": _clean(raw.get("department")),
        "office": _clean(raw.get("officeLocation")),
        "is_active": raw.get("accountEnabled") if isinstance(raw.get("accountEnabled"), bool) else None,
        "source": "microsoft_graph",
    }

    missing = [k for k in ("full_name", "email", "job_title", "department", "office", "is_active") if record[k] is None]
    record["missing_fields"] = missing
    if any(k in missing for k in ("job_title", "department")):
        warnings.append(f"missing fields set to null: {', '.join(missing)}")

    return record, warnings


def fingerprint(record: dict) -> str:
    """SHA-256 hash of the record's content. Same data -> same hash, any change -> new hash.
    Used to detect whether a user changed since it was last sent."""
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
