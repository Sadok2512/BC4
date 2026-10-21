"""Proven private positions, before either Deep tokens or staging persistence.

NFF 2.19 CAA pp24-25: context, system, type, direction, phone, own phone.
NFF 2.19 SEI: system, status, LAC, MCC, MNC, TMSI, P-TMSI,
MME group, MME code, M-TMSI. No digit-length heuristic.
"""
IDENTITY_NAMES={'phonenumber','ownphonenumber','lac','tmsi','ptmsi','mtmsi'}


def private_indices(event, count, length):
    expected={'CAA':1,'SEI':0}.get(event)
    if expected is None:return set()
    if count!=expected:
        # Unsupported private layout: never retain an unidentified private payload.
        return set(range(3,length))
    return {i for i in ({7,8} if event=='CAA' else {5,8,9,12}) if i<length}


def redact_tokens(event,tokens,count):
    masked=private_indices(event,count,len(tokens))
    return ['' if i in masked else v for i,v in enumerate(tokens)],masked


def redact_raw(event,fields):
    from app.services.task_privacy import redact_command
    result=redact_command(fields)
    if event not in {'CAA','SEI'}:return result
    try:count=int(result.get('c2') or 0)
    except (TypeError,ValueError):count=None
    indices=[int(k[1:]) for k in result if k.startswith('c') and k[1:].isdigit()]
    masked=private_indices(event,count,max(indices,default=2)+1)
    for key in result:
        normalized=''.join(c for c in key.lower() if c.isalnum())
        if normalized in IDENTITY_NAMES or key in {f'c{i}' for i in masked}:result[key]=None
    return result
