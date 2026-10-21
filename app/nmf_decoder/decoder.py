"""Total, content-preserving non-RRC parser. Unknown strings are never returned in clear."""
import csv
import hashlib
import math
import re
from dataclasses import dataclass,field
from decimal import Decimal,InvalidOperation
from . import DECODER_VERSION
from .schema import schemas,column

NUMBER=re.compile(r'^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$')
TIME=re.compile(r'^\d{2}:\d{2}:\d{2}(?:\.\d+)?$')
IDENTITIES={'#EI','#SI','#DN','#SP'}

def hashed(value):return hashlib.sha256(value.encode('utf-8')).hexdigest()[:16]

def tokenize(line):
    """Preserve CSV quoting metadata (csv.reader alone discards it)."""
    line=line.rstrip('\r\n')
    flags=[];quoted=False;at_start=True;inside=False;i=0
    while i<len(line):
        c=line[i]
        if at_start:
            quoted=c=='"';flags.append(quoted);inside=quoted;at_start=False
            if inside:i+=1;continue
        if c=='"' and inside:
            if i+1<len(line) and line[i+1]=='"':i+=2;continue
            inside=False
        elif c==',' and not inside:at_start=True
        i+=1
    if at_start:flags.append(False)
    tokens=next(csv.reader([line.rstrip('\r\n')],strict=True))
    return tokens,(flags+[False]*len(tokens))[:len(tokens)]

def numeric(raw,typ='float'):
    if raw=='':return None
    if not NUMBER.fullmatch(raw):raise ValueError('type')
    v=Decimal(raw)
    if not v.is_finite():raise ValueError('type')
    if typ=='int':
        if v!=v.to_integral_value() or abs(v)>9223372036854775807:raise ValueError('type')
        return int(v)
    value=float(v)
    if not math.isfinite(value):raise ValueError('type')
    return value

@dataclass
class Record:
    event_code:str
    capture_id:str
    seq:int
    system:int|None
    format_version:str
    decoder_version:str=DECODER_VERSION
    schema_version:str=DECODER_VERSION
    decode_status:str='ok'
    reasons:list=field(default_factory=list)
    values:dict=field(default_factory=dict)
    groups:list=field(default_factory=list)
    tokens:list=field(default_factory=list)
    field_codes:list=field(default_factory=list)
    unk_string:list=field(default_factory=list)
    quoted:list=field(default_factory=list)
    ts:str|None=None
    t_rel_s:float|None=None
    line_no:int=0
    excluded:bool=False
    context_id:int|None=None
    context_ids:list=field(default_factory=list)
    def partial(self,reason):
        self.decode_status='partial'
        if reason not in self.reasons:self.reasons.append(reason)

def decode(line,system=None,format_version='unknown',*,capture_id='',seq=0,line_no=0):
    # Only a schema-declared physical column can identify a system (NFF 2.19 §3).
    try:tokens,quoted=tokenize(line)
    except (csv.Error,StopIteration):
        r=Record('MALFORMED',capture_id,seq,None,format_version,line_no=line_no)
        r.tokens=[hashed(line)];r.quoted=[True];r.unk_string=[True];r.field_codes=['unk_MALFORMED_1'];r.partial('csv_malformed');return r
    code=tokens[0] if tokens and re.fullmatch(r'#?[A-Z][A-Z0-9_]*',tokens[0]) else 'UNKNOWN'
    r=Record(code,capture_id,seq,None,format_version,line_no=line_no)
    if code in IDENTITIES:
        r.excluded=True;r.partial('identity_header_redacted');return r
    r.ts=tokens[1] if len(tokens)>1 and TIME.fullmatch(tokens[1]) else None
    if r.ts is None:r.partial('time_missing')
    schema=schemas().get(code)
    if schema:r.schema_version=schema.get('schema_version',DECODER_VERSION)
    system_col=schema.get('system_col') if schema else None
    if isinstance(system_col,dict):
        selector=system_col['selector_col']-1
        system_col=system_col['columns'].get(tokens[selector]) if selector<len(tokens) else None
    checks=schema.get('layout_checks',[]) if schema else []
    if schema and schema.get('layout_variants'):
        variant=schema['layout_variants'];idx=variant['selector_col']-1
        checks=variant['checks'].get(tokens[idx],[]) if idx<len(tokens) else []
        if not checks:system_col=None;r.partial('context_layout_unsupported')
    layout_valid=all(len(tokens)>=c['col'] and tokens[c['col']-1]==str(c['eq']) for c in checks)
    if not layout_valid:system_col=None;r.partial('context_layout_unsupported')
    try:r.system=numeric(tokens[system_col-1],'int') if system_col and len(tokens)>=system_col else None
    except (ValueError,InvalidOperation):r.system=None
    if r.system is None:r.partial('system_missing')
    try:
        count=numeric(tokens[2],'int') or 0
        if count<0 or count>len(tokens)-3:raise ValueError()
        r.context_ids=[numeric(v,'int') for v in tokens[3:3+count]]
        if any(v is None for v in r.context_ids):raise ValueError()
        r.context_id=r.context_ids[0] if r.context_ids else None
    except (ValueError,IndexError,InvalidOperation):
        count=None;r.context_ids=[];r.partial('context_layout_unsupported')
    if schema and 'context_count' in schema and count!=schema['context_count']:
        r.system=None;r.partial('context_layout_unsupported');r.partial('system_missing')
    from .privacy import redact_tokens
    tokens,masked=redact_tokens(code,tokens,count)
    if code in {'CAA','SEI'} and count!=({'CAA':1,'SEI':0}[code]):
        r.context_id=None;r.context_ids=[]
    # Redact command XML using the existing canonical policy BEFORE hashing it.
    if code=='CMDREQ' and len(tokens)>5:
        from app.services.task_privacy import redact_command
        safe=redact_command({'service_action':tokens[4],'payload_b64':tokens[5]})
        tokens[5]=safe['payload_b64'] or ''
    r.tokens=list(tokens);r.quoted=quoted;r.field_codes=[f'unk_{code}_{i+1}' for i in range(len(tokens))];r.unk_string=[False]*len(tokens)
    known=set()
    labels=[(0,'event_code'),(1,'ts'),(2,'context_count')]
    labels += [(3+i,'context_id' if i==0 else f'context_id_{i+1}') for i in range(len(r.context_ids))]
    if system_col and r.system is not None:labels.append((system_col-1,'system'))
    for i,label in labels:
        if i<len(tokens) and (i==0 and tokens[0]==code or (i==1 and r.ts is not None) or (i>=2 and (tokens[i]=='' or NUMBER.fullmatch(tokens[i])))):
            r.field_codes[i]=label;known.add(i)
    for i in masked:
        known.add(i);r.field_codes[i]='identity_redacted'
    active=bool(schema and (schema['systems']=='any_numeric' or r.system in schema['systems']))
    if schema and 'context_count' in schema and count!=schema['context_count']:active=False
    if not layout_valid:
        active=False;r.partial('context_layout_unsupported')
    parameter_types=schema.get('parameter_types') if schema else None
    if parameter_types and (len(tokens)<parameter_types.get('col',4) or tokens[parameter_types.get('col',4)-1] not in {str(v) for v in parameter_types['values']}):
        active=False;r.partial('parameter_type_undocumented')
    if not schema:r.schema_version='none';r.partial('event_undocumented')
    elif not active:r.partial('system_undocumented')
    try:
        ver=tuple(int(p) for p in format_version.split('.'))
        if ver<(2,19):active=False;r.partial('format_unsupported')
        elif ver>(2,19):r.partial('format_extensions_unproven')
    except ValueError:active=False;r.partial('format_unknown')
    def read(f,idx,dest):
        name=column(f['code'])
        if idx>=len(tokens):r.partial('fields_truncated');return
        if idx in masked:
            dest[name]=None;return
        known.add(idx);r.field_codes[idx]=f['code']
        try:
            value=numeric(tokens[idx],f['type'])
            if value is not None:
                lo,hi=f.get('range',[None,None])
                if (lo is not None and value<lo) or (hi is not None and value>hi) or ('enum' in f and value not in f['enum']):raise ValueError('range')
            dest[name]=value
        except (ValueError,InvalidOperation) as exc:
            dest[name]=None;r.partial(f'field_{str(exc) if str(exc) in ("range","type") else "type"}:{f["code"]}')
            if tokens[idx] and not NUMBER.fullmatch(tokens[idx]):
                r.tokens[idx]=hashed(tokens[idx]);r.unk_string[idx]=True
    if active:
        for f in schema['header']:
            condition=f.get('when')
            if condition and (len(tokens)<condition['col'] or tokens[condition['col']-1]!=str(condition['eq'])):continue
            if f.get('context_count') is not None and (len(tokens)<3 or (tokens[2] or '0')!=str(f['context_count'])):
                r.partial('context_layout_unsupported');continue
            read(f,f['col']-1,r.values)
        previous_end=None
        for g in schema.get('groups', []):
            if g.get('layout')=='variable':
                try:
                    count=numeric(tokens[g['count_col']-1],'int');pos=g['start']-1
                    if count is None or count<0:raise ValueError()
                    for k in range(count):
                        if pos+1>=len(tokens):raise ValueError()
                        typ=numeric(tokens[pos],'int');width=numeric(tokens[pos+1],'int')
                        if width is None or width<0:raise ValueError()
                        values={}
                        for f in g['fields']:
                            if f.get('types') and typ not in f['types']:continue
                            idx=pos+f['offset']+(0 if f.get('part')=='header' else 2)
                            if idx>=pos+2+width:r.partial('group_width:'+g['name']);continue
                            read(f,idx,values)
                        r.groups.append(dict(group_name=g['name'],set_index=k,values=values))
                        pos+=2+width
                        if pos>len(tokens):raise ValueError()
                except (ValueError,IndexError,InvalidOperation):r.partial('group_layout:'+g['name'])
                continue
            start=g['start']
            try:
                if start=='previous_end':idx=previous_end
                elif isinstance(start,dict):
                    h=start['header_col']-1;size=numeric(tokens[h],'int');idx=h+1+size
                    if size<0:raise ValueError()
                else:idx=start-1
                if idx is None or idx<0 or idx+1>=len(tokens):raise ValueError()
                count=numeric(tokens[idx],'int');width=numeric(tokens[idx+1],'int')
                if count is None or width is None or count<0 or width<0 or (count>0 and width==0):raise ValueError()
            except (ValueError,IndexError,TypeError):r.partial('group_layout:'+g['name']);break
            for offset,key in [(0,'count_code'),(1,'params_code')]:
                known.add(idx+offset);r.field_codes[idx+offset]=g[key];r.values[column(g[key])]=count if offset==0 else width
            first=idx+2;previous_end=first+count*width
            if previous_end>len(tokens):r.partial('group_truncated:'+g['name'])
            available=min(count,(max(0,len(tokens)-first)+max(width,1)-1)//max(width,1))
            for k in range(available):
                values={};base=first+k*width
                for j,f in enumerate(g['fields'][:width]):read(f,base+j,values)
                if width<len(g['fields']):r.partial('group_width:'+g['name'])
                r.groups.append(dict(group_name=g['name'],set_index=k,values=values))
    for i,value in enumerate(tokens):
        if i in known:continue
        if quoted[i] or (value!='' and not NUMBER.fullmatch(value)):
            r.tokens[i]=hashed(value);r.unk_string[i]=True
        # No numeric digit-length heuristic. Integers such as 162119527 survive verbatim.
    if any(c.startswith('unk_') for c in r.field_codes):r.partial('unknown_fields')
    return r
