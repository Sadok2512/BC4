"""Sanitized NAS message decoder.

Addresses the "SIGNALING FULL DECODE LTE/NR" mission:
  - Decode technical NAS IEs (EMM/ESM/5GMM/5GSM) via pycrate 0.8.1.
  - Keep CLAUDE.md P0 subscriber-identity confidentiality: redact IMSI,
    IMEI/IMEISV, MSISDN, GUTI/5G-GUTI, M-TMSI, S-TMSI, SUPI, SUCI, PEI,
    MAC/MACShort, RAND, AUTN, RES/XRES/AUTS, KSI value, keys (K*), and
    all mobile-identity containers.
  - Never fabricate an IE. If pycrate fails or an IE is not present in
    the payload, do not synthesize it.
  - Preserve the original payload only in-memory; never return the raw
    hex in the response.

Output per message::

    {
      "status": "FULLY_DECODED" | "PARTIALLY_DECODED" | "REDACTED" | "UNSUPPORTED",
      "parameters": [
        {"path": "...", "name": "...", "value": "...", "safe": bool,
         "redacted_reason": "..." | None, "spec": "3GPP TS ... §..."},
        ...
      ],
      "pdu_class": "EMMServiceRequest",
      "reason": "...",         # only when UNSUPPORTED
    }

The decoder is read-only ; it does not persist, cache, or ship raw hex.
"""
from __future__ import annotations

import re
from typing import Any

# pycrate_mobile.NAS exposes parse_NAS_MO / parse_NAS_MT and the PDU
# class hierarchy.  CryptoMobile is optional and only required to
# *decrypt* NAS payloads — we never do that.
try:
    from pycrate_mobile import NAS as _NAS  # type: ignore[import-untyped]
    _PYCRATE_AVAILABLE = True
except Exception:  # pragma: no cover
    _NAS = None  # type: ignore[assignment]
    _PYCRATE_AVAILABLE = False


# IE names that MUST never leave the decoder (3GPP TS 24.301 §9.9 for EMM
# and §10.5 for 24.008 UMTS; TS 24.501 §9.11 for 5GMM/5GSM).  Match on
# case-insensitive substring to cover pycrate's dotted class names.
_REDACT = re.compile(
    r"""
    IMSI | IMEI | IMEISV | MSISDN | SUPI | SUCI | PEI
    | GUTI | MTMSI | STMSI | TMSI | NRI | EPSID
    | MobileId | MobID
    | \bMAC\b | MACShort | NAS_MAC
    | RAND | AUTN | \bRES\b | XRES | AUTS | AUTH[A-Z_]*Response
    | KASME | KAMF | KSEAF | KAUSF | KSIasme | KSIsgsn
    | NAS_KSI | \bKSI\b
    | NASKey
    | EmergencyNumber
    """,
    re.IGNORECASE | re.VERBOSE,
)


# IE names that are safe to expose verbatim (technical/protocol only).
_SAFE_NAME_HINT = re.compile(
    r"""
    MessageType | ProtDisc | ProtocolDiscriminator | SecHdr
    | EMMCause | ESMCause | ServiceType
    | EpsAttachType | AttachType | EpsUpdateType | UpdateType | DetachType
    | EPSBearerIdentity | BearerId | BearerIdentity
    | PTI | ProcedureTransactionIdentity
    | QoS | ApnAmbr | EPSqualityOfService
    | ESMInformationTransferFlag
    | PDNType | RequestType
    | NAS[-_]?SecurityAlgorithms
    | UESecurityCapability
    | SpareHalfOctet | Spare
    | SeqnShort | Seqn
    | PLMN | PLMNList
    | Type   # pycrate generic 'Type' is almost always a protocol enum
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _is_sensitive(name: str) -> bool:
    """True if the IE name matches the redact pattern."""
    return bool(_REDACT.search(name))


def _is_known_safe(name: str) -> bool:
    """True if the IE name is explicitly on the safe allowlist."""
    return bool(_SAFE_NAME_HINT.search(name))


def _value_repr(obj: Any) -> str:
    """Human-readable value from a pycrate Atom.

    Strip bytes-literal `b'...'` representations entirely — they always
    carry raw material (potentially identity bits).  Numeric values and
    short enums pass through."""
    try:
        v = obj.get_val()
    except Exception:
        return "—"
    if isinstance(v, (bytes, bytearray)):
        return f"<binary · {len(v)} bytes · redacted>"
    if isinstance(v, (list, tuple)):
        # Enums come as (name, int) tuples in pycrate; keep the name only.
        if len(v) == 2 and isinstance(v[0], str) and isinstance(v[1], int):
            return f"{v[0]} ({v[1]})"
        return repr(v)
    return str(v)


def _walk(obj: Any, path: str, params: list[dict], redacted_count: list[int]) -> None:
    """Recursively walk a pycrate PDU object, emitting one dict per leaf.

    Containers (Envelope/Sequence) produce children; atoms produce one
    parameter row with either the value or a REDACTED marker."""
    name = getattr(obj, "_name", type(obj).__name__)
    full_path = f"{path}/{name}" if path else name

    children = []
    # Containers expose .__iter__ returning children in pycrate.
    try:
        children = list(iter(obj))
    except TypeError:
        children = []

    if children and not hasattr(obj, "get_bl"):
        # Looks like a container but not iterable by atom; keep walking.
        for ch in children:
            _walk(ch, full_path, params, redacted_count)
        return

    if children:
        for ch in children:
            _walk(ch, full_path, params, redacted_count)
        return

    # Leaf atom — check the FULL PATH (not just the leaf name) so that any
    # sensitive ancestor container (ex. OldGUTI, NAS_KSI, TMSIBasedNRICont)
    # redacts all its descendants recursively.
    sensitive = _is_sensitive(full_path)
    if sensitive:
        redacted_count[0] += 1
        params.append({
            "path": full_path,
            "name": name,
            "value": None,
            "safe": False,
            "redacted_reason": "subscriber-identity or cryptographic material (CLAUDE.md P0)",
        })
        return
    # Everything else: show value.
    params.append({
        "path": full_path,
        "name": name,
        "value": _value_repr(obj),
        "safe": True,
        "redacted_reason": None,
    })


def decode(payload_hex: str, direction: str | None, system: str | None) -> dict:
    """Decode a NAS payload and return sanitized parameters.

    direction: 'UL' / 'DL' (controls MO vs MT parse order attempt)
    system: 'LTE' / 'NR' / 'UMTS' (informational — pycrate auto-detects)"""
    if not _PYCRATE_AVAILABLE:
        return {"status": "UNSUPPORTED", "parameters": [], "pdu_class": None,
                "reason": "pycrate not available"}
    if not payload_hex or not re.fullmatch(r"[0-9A-Fa-f]+", payload_hex):
        return {"status": "UNSUPPORTED", "parameters": [], "pdu_class": None,
                "reason": "payload not hexadecimal"}
    try:
        payload = bytes.fromhex(payload_hex)
    except Exception as e:
        return {"status": "UNSUPPORTED", "parameters": [], "pdu_class": None,
                "reason": f"hex decode failed: {e}"}

    # Prefer MO when the message came from UE (UL), MT otherwise. Try both
    # before giving up — pycrate returns None + err code when unsupported.
    attempts = ("MO", "MT") if direction == "UL" else ("MT", "MO")
    pdu = None
    last_err = None
    for mode in attempts:
        try:
            parsed, err = getattr(_NAS, f"parse_NAS_{mode}")(payload)
            if parsed is not None:
                pdu = parsed
                break
            last_err = err
        except Exception as e:  # pragma: no cover
            last_err = str(e)
    if pdu is None:
        return {"status": "UNSUPPORTED", "parameters": [], "pdu_class": None,
                "reason": f"pycrate parse failed (err={last_err})"}

    params: list[dict] = []
    redacted_count = [0]
    try:
        _walk(pdu, "", params, redacted_count)
    except Exception as e:  # pragma: no cover
        return {"status": "UNSUPPORTED", "parameters": [], "pdu_class": type(pdu).__name__,
                "reason": f"walk failed: {e}"}

    # Final sanitation sweep: any leftover identity-looking string in a
    # value (should not happen after walking atoms, but belt-and-braces).
    for p in params:
        if p["value"] and isinstance(p["value"], str) and _REDACT.search(p["value"]):
            p["value"] = None
            p["safe"] = False
            p["redacted_reason"] = "value contained identity substring (defensive)"
            redacted_count[0] += 1

    safe_count = sum(1 for p in params if p["safe"])
    if not params:
        status = "UNSUPPORTED"
    elif redacted_count[0] == 0:
        status = "FULLY_DECODED"
    elif safe_count == 0:
        status = "REDACTED"
    else:
        status = "PARTIALLY_DECODED"

    return {
        "status": status,
        "parameters": params,
        "pdu_class": type(pdu).__name__,
        "reason": None,
    }
