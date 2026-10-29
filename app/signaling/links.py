"""Explicit event→messages linking rules for the Signaling timeline.

Spec: /home/devmat/BC4/specs/signaling_timeline.html.

Every link carries:
  - pivot_seq      : the single most relevant message (or None if none in window)
  - linked_seqs    : all messages pulled by the rule (ordered by seq)
  - link_rule      : the identifier of the rule applied
  - seq_gap        : max(|row.seq - event.seq|) across linked_seqs,
                     or the gap to the pivot when linked_seqs is empty
                     and pivot_seq is set; None otherwise.

Ordering is strictly (capture_id, seq). Timestamps are never used to pick a
pivot or a linked message. The maximum sequence gap allowed per rule caps
the "noise window" — a link farther than that is dropped and reported as
"no_message_in_window".

BC1 dictionary routes `/dict/v2/scells`, `/dict/v2/rlf`, `/dict/v2/endc`
are NOT present in the current OpenAPI (audited 2026-10-21). For rules
that would depend on them we read `param_occurrence` directly, filtered by
the ASN.1 path pattern spelled out in each rule entry.

If a target IE is not even present in `param_occurrence` for any project
(ex. nr-Config-r15, sCellToAddModList-r10 absent of current dict output),
the rule stays declared but its lookup returns a `no_dict_support` link
rule and empty linked_seqs. Nothing is fabricated to fill the gap.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable


@dataclass(frozen=True)
class LinkContext:
    """Everything a rule needs to make a decision without re-querying twice."""
    project_id: str
    capture_id: str
    # Preloaded signaling rows (dicts from svc.population) indexed by seq
    # so we can enumerate messages around an event by sequence order.
    rows_by_seq: dict[int, dict]
    # Sorted list of seqs for quick window lookups.
    seqs: list[int]
    # DB session for ad-hoc param_occurrence lookups.
    db: object


def _window(ctx: LinkContext, around_seq: int, max_gap: int,
            predicate: Callable[[dict], bool]) -> Iterable[dict]:
    """Yield rows whose seq falls within [around_seq - max_gap, around_seq + max_gap]
    and that satisfy predicate, ordered by seq."""
    lo, hi = around_seq - max_gap, around_seq + max_gap
    # The seqs list is sorted ; use linear bounded scan since max_gap stays
    # small (<=50 default) and the hot captures are O(10 000) rows.
    for s in ctx.seqs:
        if s < lo:
            continue
        if s > hi:
            break
        row = ctx.rows_by_seq[s]
        if predicate(row):
            yield row


def _is_rrc_reconfig_with_mobility(ctx: LinkContext, row: dict) -> bool:
    """RRCConnectionReconfiguration qui porte mobilityControlInfo.

    Résolu via param_occurrence (le path exact est connu depuis l'audit :
    il contient `mobilityControlInfo`). Pas de ts, pas d'invention."""
    if row['protocol'] != 'RRC LTE':
        return False
    name = row['message_name'] or ''
    if 'Reconfiguration' not in name:
        return False
    # SOURCE_SQL prepares this exact EXISTS while the capture snapshot is
    # loaded.  Consuming it here keeps projection CPU outside a database
    # transaction during import and avoids one query per HOA/HOS candidate.
    return bool(row.get('ho_reconfiguration'))


def _link_ho(ctx: LinkContext, event_row: dict) -> dict:
    """HOA → pivot = last RRCConnectionReconfiguration mobilityControlInfo ≤ 50 seq BEFORE HOA ;
    linked = ...Complete, MeasurementReport + MEI just before, RACHI just after.

    Spec: /signaling_timeline.html § règles."""
    max_gap = 50
    seq = event_row['seq']
    # Pivot
    pivot = None
    for s in reversed(ctx.seqs):
        if s > seq:
            continue
        if seq - s > max_gap:
            break
        if _is_rrc_reconfig_with_mobility(ctx, ctx.rows_by_seq[s]):
            pivot = s
            break
    linked: list[int] = []
    if pivot is not None:
        linked.append(pivot)
    # Complete, MeasurementReport, MEI, RACHI in the window
    for s in ctx.seqs:
        if s < seq - max_gap:
            continue
        if s > seq + max_gap:
            break
        row = ctx.rows_by_seq[s]
        name = (row['message_name'] or '').lower()
        if row['event_code'] == 'MEI' and s < seq:
            linked.append(s)
        elif row['event_code'] == 'RACHI' and s > seq:
            linked.append(s)
        elif 'reconfigurationcomplete' in name:
            linked.append(s)
        elif 'measurementreport' in name:
            linked.append(s)
    linked = sorted(set(linked))
    gap = max((abs(s - seq) for s in linked), default=None)
    return dict(pivot_seq=pivot, linked_seqs=linked,
                link_rule='ho_reconfig_mobility', seq_gap=gap)


def _link_rrc_setup(ctx: LinkContext, event_row: dict) -> dict:
    """RRA → RRCConnectionRequest, RRC → RRCConnectionSetup, RRD → SetupComplete."""
    max_gap = 20
    code = event_row['event_code']
    name_target = {
        'RRA': 'rrcconnectionrequest',
        'RRC': 'rrcconnectionsetup',
        'RRD': 'rrcconnectionsetupcomplete',
    }.get(code)
    if not name_target:
        return dict(pivot_seq=None, linked_seqs=[], link_rule='no_rule', seq_gap=None)
    seq = event_row['seq']
    pivot = None
    best_gap = None
    for row in _window(ctx, seq, max_gap,
                       lambda r: name_target in (r['message_name'] or '').lower()):
        g = abs(row['seq'] - seq)
        if best_gap is None or g < best_gap:
            pivot = row['seq']
            best_gap = g
    linked = [pivot] if pivot is not None else []
    return dict(pivot_seq=pivot, linked_seqs=linked,
                link_rule='rrc_setup_message', seq_gap=best_gap)


def _link_rlf(ctx: LinkContext, event_row: dict) -> dict:
    """RLF marker → ReestablishmentRequest in window."""
    max_gap = 50
    seq = event_row['seq']
    pivot = None
    for row in _window(ctx, seq, max_gap,
                       lambda r: 'reestablishmentrequest' in (r['message_name'] or '').lower()):
        pivot = row['seq']
        break
    linked = [pivot] if pivot is not None else []
    gap = abs(pivot - seq) if pivot is not None else None
    return dict(pivot_seq=pivot, linked_seqs=linked,
                link_rule='rlf_reestab_request', seq_gap=gap)


def _link_pass_through(_ctx: LinkContext, event_row: dict) -> dict:
    """Rule for state events (call/data/attach/bearer markers) that pivot on
    themselves — the event IS its own anchor. No message is pulled from the
    RRC/NAS stream because the appartenance would require SIPSM/task payload
    which is not in the signaling contract."""
    return dict(pivot_seq=event_row['seq'], linked_seqs=[event_row['seq']],
                link_rule='pivot_on_state_event', seq_gap=0)


def _link_no_dict_support(_ctx: LinkContext, event_row: dict) -> dict:
    """SgNB addition / SCell add rules: the dict decoder does not currently
    expose `nr-Config-r15` nor `sCellToAddModList-r10` paths. Rule stays
    declared but links nothing — no invention."""
    return dict(pivot_seq=None, linked_seqs=[], link_rule='no_dict_support',
                seq_gap=None)


# ---------------------------------------------------------------------------
# Rule table: event_code (state event) -> handler
# Rules whose event comes from a reconstructed procedure are indexed by
# procedure type below.
# ---------------------------------------------------------------------------
EVENT_RULES: dict[str, Callable[[LinkContext, dict], dict]] = {
    'HOA': _link_ho,
    'HOS': _link_ho,
    'HOI': _link_pass_through,
    'RRA': _link_rrc_setup,
    'RRC': _link_rrc_setup,
    'RRD': _link_rrc_setup,
    'CAA': _link_pass_through,
    'CAC': _link_pass_through,
    'CAD': _link_pass_through,
    'DAA': _link_pass_through,
    'DAC': _link_pass_through,
    'DAD': _link_pass_through,
    'GAA': _link_pass_through,
    'GAC': _link_pass_through,
    'GAD': _link_pass_through,
    'PBA': _link_pass_through,
    'PBC': _link_pass_through,
    'PBD': _link_pass_through,
    'RACHI': _link_pass_through,
    'CREL': _link_pass_through,
    'MEI': _link_pass_through,
    'LOCK': _link_pass_through,
    'MARK': _link_pass_through,
    'SCELLMOD': _link_no_dict_support,
}


# ---------------------------------------------------------------------------
# Lane mapping (spec §ruban): 8 couloirs.
# ---------------------------------------------------------------------------
EVENT_LANE: dict[str, str] = {
    # Connexion
    'RRA': 'connexion', 'RRC': 'connexion', 'RRD': 'connexion',
    # Mobilité
    'HOA': 'mobilite', 'HOS': 'mobilite', 'HOI': 'mobilite', 'MEI': 'mobilite',
    # 5G / EN-DC — events currently sourced from BC2 markers only (SCELLMOD stub)
    # Carrier Aggregation
    'SCELLMOD': 'ca',
    # Services (voice / data / packet bearer / attach)
    'CAA': 'services', 'CAC': 'services', 'CAD': 'services',
    'DAA': 'services', 'DAC': 'services', 'DAD': 'services',
    'GAA': 'services', 'GAC': 'services', 'GAD': 'services',
    'PBA': 'services', 'PBC': 'services', 'PBD': 'services',
    # Accès / échecs
    'RACHI': 'acces', 'CREL': 'acces',
    # Contexte
    'LOCK': 'contexte', 'MARK': 'contexte',
}


# Procedures contributed by reconstruct() → lane + kind='bar' with duration.
PROCEDURE_LANE: dict[str, str] = {
    'rrc_setup': 'connexion',
    'rrc_connection': 'connexion',
    'ho': 'mobilite',
    'call': 'services',
    'data_session': 'services',
    'attach': 'services',
    'bearer': 'services',
    'reestablishment': 'acces',
}


# All eight lane keys allowed in the response (filter param whitelist).
LANES = ('radio', 'connexion', 'mobilite', 'endc', 'ca', 'services', 'acces', 'contexte')
