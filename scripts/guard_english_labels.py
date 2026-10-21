"""Manual presentation-only invariant: python scripts/guard_english_labels.py."""
import sys
from pathlib import Path
from copy import deepcopy
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.kpi.english import english_response
source={'family':'Accessibilité','name':'Débit APP DL agrégé','nature':'Compteur','reason':None,
        'code':'LTE_RRC_ATTEMPTS','value':0,'n':1897,'result_id':'test-proof',
        'series':[{'value':None,'seq':65,'label':'Débits par couche'}],
        'source':'measurement_points.rsrp','raw':'Voix','unit':'dBm'}
before=deepcopy(source);translated=english_response(source)
assert source==before
assert translated['family']=='Accessibility'
assert translated['series'][0]['label']=='Throughput by layer'
for k in ['code','value','n','result_id','source','raw','unit','reason']:assert source[k]==translated[k],k
assert translated['series'][0]['value'] is None
assert translated['series'][0]['seq']==65
print('PASS: English labels; source catalogue, values, nulls, codes, units and result_id preserved')
