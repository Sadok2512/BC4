"""Capture-local Nemo context state machines, preserving two distinct HO clocks."""
from decimal import Decimal

RULES={
    'ho':('HOA','HOS'), 'call':('CAA','CAC','CAD'),
    'data_session':('DAA','DAC','DAD'), 'rrc_connection':('RRA','RRC','RRD'),
    'attach':('GAA','GAC'), 'bearer':('PBA','PBC','PBD'),
}


class Pairs:
    def __init__(self):self.active={};self.completed=[];self.ho={}

    def finish(self,key,end=None,cause=None):
        a=self.active.pop(key);start=a['start'];duration=None
        if end and start.t_rel_s is not None and end.t_rel_s is not None:
            delta=(Decimal(str(end.t_rel_s))-Decimal(str(start.t_rel_s)))*1000
            if delta>=0:duration=float(delta)
            else:cause='capture_clock_regression'
        # A boundary pair proves completion, not a successful status/cause code.
        outcome='incomplete' if end is None or cause else 'completed'
        if key[0]=='ho' and end and not cause:outcome='ok'  # HOS explicitly means success.
        if end and not cause and key[0]=='rrc_connection':
            status=end.values.get('rrd_rrc_rel_status')
            outcome={1:'ok',2:'fail'}.get(status,'completed')
            raw=end.values.get('rrd_rrc_rel_cause')
            cause=f'rrd.rrc_rel_cause={raw}' if raw is not None else None
        if end and not cause and key[0]=='call':
            status=end.values.get('cad_cs_disc_status')
            outcome={1:'ok',2:'fail',3:'fail'}.get(status,'completed')
            raw=end.values.get('cad_volte_cause')
            cause=f'cad.volte_cause={raw}' if raw is not None else None
        row=dict(type=key[0],context_id=start.context_id,seq_start=start.seq,
                 seq_end=end.seq if end else None,seq_hoi=None,duration_nemo_ms=duration,
                 ho_duration_nemo_ms=duration if key[0]=='ho' else None,
                 ho_duration_hoi_ms=None,outcome=outcome,cause=cause)
        self.completed.append(row)
        if key[0]=='ho':self.ho[start.context_id]=row

    def add(self,r):
        if r.event_code=='HOI':
            row=self.ho.get(r.context_id)
            if row and row['seq_end'] is not None and row['seq_hoi'] is None and r.seq>row['seq_end']:
                row['seq_hoi']=r.seq;row['ho_duration_hoi_ms']=r.values.get('hoi_ho_duration')
            return
        for kind,stages in RULES.items():
            key=(kind,r.context_id)
            if r.event_code==stages[0]:
                if key in self.active:self.finish(key,cause='repeated_start_before_completion')
                if kind=='ho':self.ho.pop(r.context_id,None)
                # No context means no proven association (DAA in TEST2 is one such case).
                if r.context_id is None:
                    self.active[key]={'start':r,'stage':1};self.finish(key,cause='context_missing');continue
                self.active[key]={'start':r,'stage':1}
            elif key in self.active and r.event_code==stages[self.active[key]['stage']]:
                self.active[key]['stage']+=1
                if self.active[key]['stage']==len(stages):self.finish(key,r)

    def rows(self):
        for key in list(self.active):self.finish(key,cause='missing_terminal_event')
        return sorted(self.completed,key=lambda r:(r['seq_start'],r['type']))
