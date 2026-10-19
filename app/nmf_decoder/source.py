"""Source order and physical line provenance; ASN.1 is deliberately outside this component."""
import hashlib
from decimal import Decimal
from .decoder import decode,tokenize,TIME
SIGNALLING={'RRCSM','L3SM','L2SM','MACSM','SIPSM'}  # Existing BC1 boundary, unchanged.

def records(path,capture_id,expected_sha=None):
    if expected_sha:
        digest=hashlib.sha256()
        with open(path,'rb') as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
        if digest.hexdigest()!=expected_sha:raise ValueError('source_sha_mismatch')
    seq=0;origin=None;previous=None;version='unknown'
    with open(path,encoding='latin-1') as stream:
        for line_no,line in enumerate(stream,1):
            if not line.strip():continue
            if line.startswith('#'):
                if line.startswith('#FF,'):
                    try:version=tokenize(line)[0][3]
                    except (ValueError,IndexError):version='unknown'
                # #EI/#SI/#DN never enter a record/table, even as unknown hashes.
                continue
            seq+=1
            try:
                fields,_=tokenize(line)
                ts=fields[1] if len(fields)>1 else ''
            except Exception:fields=[];ts=''
            sec=None
            if TIME.fullmatch(ts):
                h,m,s=ts.split(':');sec=Decimal(h)*3600+Decimal(m)*60+Decimal(s)
                if origin is None:origin=sec
            if fields and fields[0] in SIGNALLING:continue
            r=decode(line,format_version=version,capture_id=capture_id,seq=seq,line_no=line_no)
            if sec is not None:
                r.t_rel_s=float(sec-origin)
                if previous is not None and sec<previous:r.partial('time_regression')
                previous=sec
            yield r
