"""A message's existing dictionary occurrences; no decode/populate writes.

The dictionary walk removes sensitive IEs, so its absence of identifiers is
NOT evidence that a raw PDU is safe. Inspect the unfiltered ASN.1 value in an
isolated PDU before returning any hex; opaque/undecodable payloads fail closed.
Never log decoded values or rejected payloads.
"""
from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.dict.category_mapping import identifier_path_rule, resolve_mapping
from app.dict.decode import DENY, path_matches_deny, resolve_pdu, walk
from app.schemas.signaling_message import SignalingMessage, SignalingParameter

EVENT_SQL = """SELECT id,event_code,system,channel,direction,message,payload_hex
FROM stg_event WHERE project_id=:pid AND capture_id=:cap AND seq=:seq
ORDER BY id LIMIT 2"""
OCCURRENCES_SQL = """SELECT path,value,value_converted,unit_converted,display_name,
system,discriminators,is_identifier,functional_group
FROM param_occurrence WHERE project_id=:pid AND stg_event_id=:event_id ORDER BY path"""
# Explicit G18b defense in addition to the CONTENT inspection below.
_RESTRICTED_MESSAGES = frozenset({
    'rrcconnectionrequest', 'rrcsetuprequest', 'rrcconnectionsetupcomplete',
    'rrcsetupcomplete', 'setupcomplete', 'ulinformationtransfer', 'dlinformationtransfer',
})


def sensitive_path(path: str) -> bool:
    return bool(any(DENY.search(p) for p in path.split('/')) or identifier_path_rule(path))


def inspect_content(value: Any, path: tuple[str, ...] = ()) -> str | None:
    """Return only a generic reason, never a sensitive path or value."""
    if sensitive_path('/'.join(path)):
        return 'identity_ie_present'
    if isinstance(value, dict):
        for key, item in value.items():
            reason = inspect_content(item, (*path, str(key)))
            if reason:
                return reason
    elif isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], str):
        return inspect_content(value[1], (*path, value[0]))
    elif isinstance(value, list):
        for item in value:
            reason = inspect_content(item, path)
            if reason:
                return reason
    elif isinstance(value, (bytes, bytearray)):
        if value:
            return 'opaque_ie_identity_not_excluded'
    elif isinstance(value, tuple):
        if not (len(value) == 2 and all(isinstance(v, int) for v in value)):
            return 'unknown_asn1_value_identity_not_excluded'
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        return 'unknown_asn1_value_identity_not_excluded'
    return None


def safe_hex(event: dict, occurrences: list[dict], protocol: str) -> tuple[str | None, int | None, str | None]:
    payload = event['payload_hex']
    if not payload:
        return None, None, 'payload_unavailable'
    # Only hexadecimal octets, never arbitrary staging text.
    compact = ''.join(payload.split())
    if not compact or len(compact) % 2 or not re.fullmatch(r'[0-9a-fA-F]+', compact):
        return None, None, 'invalid_hex_payload'
    size = len(compact) // 2
    if (event['message'] or '').casefold() in _RESTRICTED_MESSAGES:
        return None, size, 'identity_bearing_message'
    if any(row['is_identifier'] or sensitive_path(row['path']) for row in occurrences):
        return None, size, 'identity_ie_present'
    if protocol == 'nas':
        return None, size, 'nas_identity_absence_not_proven'
    if size > 262144:
        return None, size, 'payload_too_large_for_identity_check'
    try:
        template = resolve_pdu(event['system'], event['channel'], event['direction'], event['message'] or '')
        if template is None:
            return None, size, 'unsupported_pdu_identity_not_excluded'
        pdu = deepcopy(template)
        raw = bytes.fromhex(compact)
        pdu.from_uper(raw)
        reason = inspect_content(pdu.get_val())
        if reason:
            return None, size, reason
        # Reject opaque suffixes / partial decoding, even if the parsed prefix is safe.
        if pdu.to_uper() != raw:
            return None, size, 'payload_roundtrip_mismatch'
    except Exception:
        # Exception messages may contain ASN.1 values: neither log nor return them.
        return None, size, 'decode_failed_identity_not_excluded'
    return compact, size, None


def render_text(tree: list[SignalingParameter]) -> str:
    lines: list[str] = []
    previous: list[str] = []
    for item in tree:
        parents = item.path.split('/')[:-1]
        common = 0
        while common < min(len(parents), len(previous)) and parents[common] == previous[common]:
            common += 1
        for depth in range(common, len(parents)):
            lines.append('  ' * depth + parents[depth])
        value = item.value if item.value is not None else '—'
        lines.append('  ' * len(parents) + f'{item.name}: {value}' + (f' {item.unit}' if item.unit else ''))
        previous = parents
    return '\n'.join(lines)


def sanitized_payload_tree(event: dict, mappings: list[dict], categories: dict[str, str]) -> list[SignalingParameter]:
    """Decode safe RRC leaves when the persisted dictionary has no rows.

    Some identity-bearing messages (notably LTE SetupComplete) are absent from
    ``param_occurrence`` because their NAS container is deliberately excluded.
    That must not hide unrelated RRC leaves.  Decode a private PDU instance,
    reuse the dictionary walk/deny rules, then apply the independent path
    identity rule before returning anything.  The payload and opaque byte
    containers remain unavailable.
    """
    payload = event.get('payload_hex')
    if event.get('event_code') != 'RRCSM' or not payload:
        return []
    try:
        compact = ''.join(payload.split())
        if not compact or len(compact) % 2 or not re.fullmatch(r'[0-9a-fA-F]+', compact):
            return []
        template = resolve_pdu(
            event.get('system'), event.get('channel'), event.get('direction'), event.get('message') or '',
        )
        if template is None:
            return []
        pdu = deepcopy(template)
        pdu.from_uper(bytes.fromhex(compact))
        flattened: list[tuple[list[str], Any]] = []
        walk(pdu.get_val(), [], flattened)
    except Exception:
        # Fail closed. Exception strings can contain decoded values.
        return []

    result: list[SignalingParameter] = []
    for parts, value in flattened:
        if not parts or path_matches_deny(parts):
            continue
        path = '/'.join(parts)
        if sensitive_path(path):
            continue
        match = resolve_mapping(event.get('system'), path, None, mappings)
        result.append(SignalingParameter(
            path=path,
            name=parts[-1],
            value=None if value is None else str(value),
            unit=None,
            display_name=None,
            category=categories.get(match['category_id']) if match else None,
        ))
    return result


def decoded_message(db: Session, project_id: str, capture_id: str, seq: int) -> SignalingMessage:
    events = list(db.execute(text(EVENT_SQL), {'pid': project_id, 'cap': capture_id, 'seq': seq}).mappings())
    if not events:
        raise HTTPException(404, detail={'code': 'MESSAGE_NOT_FOUND'})
    if len(events) > 1:
        raise HTTPException(409, detail={'code': 'AMBIGUOUS_MESSAGE_SEQUENCE'})
    event = dict(events[0])
    if event['event_code'] == 'L3SM':
        protocol = 'nas'
    elif event['event_code'] == 'RRCSM' and event['system'] in ('LTE', 'NR'):
        protocol = {'LTE': 'rrc_lte', 'NR': 'rrc_nr'}[event['system']]
    else:
        raise HTTPException(422, detail={'code': 'SIGNALING_PROTOCOL_UNSUPPORTED'})
    rows = [dict(row) for row in db.execute(text(OCCURRENCES_SQL), {'pid': project_id, 'event_id': event['id']}).mappings()]
    mappings = [dict(row) for row in db.execute(text('SELECT * FROM dict_category_map')).mappings()]
    categories = {row['id']: row['label'] for row in db.execute(text('SELECT id,label FROM dict_category')).mappings()}
    tree = []
    for row in rows:
        if row['is_identifier'] or sensitive_path(row['path']):
            continue
        match = resolve_mapping(row['system'], row['path'], row['discriminators'], mappings)
        tree.append(SignalingParameter(
            path=row['path'], name=row['path'].rsplit('/', 1)[-1],
            value=row['value_converted'] if row['value_converted'] is not None else row['value'],
            unit=row['unit_converted'], display_name=row['display_name'],
            category=categories.get(match['category_id']) if match else row['functional_group'],
        ))
    if not tree and protocol in ('rrc_lte', 'rrc_nr'):
        tree = sanitized_payload_tree(event, mappings, categories)
    payload, size, reason = safe_hex(event, rows, protocol)
    return SignalingMessage(
        project_id=project_id, capture_id=capture_id, seq=seq,
        message_name=event['message'], protocol=protocol, direction=event['direction'],
        channel=event['channel'], size_bytes=size, tree=tree, text=render_text(tree),
        hex=payload, reason=reason,
        tree_reason=None if tree else 'no_admissible_dictionary_occurrences',
    )
