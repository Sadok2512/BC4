"""User-supplied canonical path references, including absent project paths."""
import csv,json
from pathlib import Path
A=Path(__file__).resolve().parent
S=A.parents[1]/'app/dict/config/categories_v22.json'
seed=json.loads(S.read_text()); rows=list(csv.DictReader((A/'path-populations.csv').open()))
R='rrcConnectionReconfiguration/rrcConnectionReconfiguration-r8/'
D='radioResourceConfigDedicated/'
M='measConfig/'
report=M+'reportConfigToAddModList/[*]/reportConfig/'
a5=[report+'reportConfigEUTRA/triggerType/event/eventId/eventA5/a5-Threshold'+i+'/threshold-RSRP' for i in ['1','2']]
sp='spCellConfig/spCellConfigDedicated/'
def item(sub,*paths,tech='LTE'):return (sub,tech,list(paths))
answers={
'layering-connected-01':item('layering-connected.layers',M+'measObjectToAddModList/[*]/measObject/measObjectEUTRA/carrierFreq'),
'layering-connected-02':item('layering-connected.layers',M+'measObjectToAddModList/[*]/measObject/measObjectNR-r15/carrierFreq-r15'),
'layering-connected-03':item('layering-connected.switch',*[M+'measIdToAddModList/[*]/'+x for x in ['measId','measObjectId','reportConfigId']]),
'layering-connected-05':item('mobility.inter',*a5),
'layering-connected-06':item('layering-connected.ca','sCellToAddModList-r10/[*]/cellIdentification-r10/dl-CarrierFreq-r10'),
'layering-connected-07':item('layering-connected.endc','nr-Config-r15/setup/nr-SecondaryCellGroupConfig-r15'),
'layering-connected-08':item('layering-connected.endc','nr-Config-r15/setup/p-MaxEUTRA-r15'),
'mobility-06':item('mobility.inter',*a5),
'mobility-10':item('mobility.inter-rat',report+'reportConfigInterRAT/triggerType/event/eventId/eventB1-NR-r15/b1-ThresholdNR-r15/nr-RSRP-r15'),
'mimo-ca-02':item('mimo-ca.antennas',D+'physicalConfigDedicated/antennaInfo/explicitValue/codebookSubsetRestriction',D+'physicalConfigDedicated/antennaInfo-r10/explicitValue-r10/codebookSubsetRestriction-r10'),
'mimo-ca-04':item('mimo-ca.scell','sCellToAddModList-r10/[*]/sCellIndex-r10'),
'rlc-pdcp-01':item('rlc-pdcp.bearers',D+'drb-ToAddModList/[*]/rlc-Config'),
'drx-08':item('drx.nr','mac-CellGroupConfig/drx-Config/setup/drx-LongCycleStartOffset',tech='NR'),
'mac-09':item('mac.sr','mac-CellGroupConfig/schedulingRequestConfig/schedulingRequestToAddModList/[*]/sr-TransMax',tech='NR'),
'mimo-ca-05':item('mimo-ca.nr',sp+'uplinkConfig/initialUplinkBWP/pusch-Config/setup/maxRank',tech='NR'),
'mimo-ca-06':item('mimo-ca.nr',sp+'csi-MeasConfig/setup/nzp-CSI-RS-ResourceToAddModList/[*]/resourceMapping/nrofPorts',tech='NR'),
'mimo-ca-07':item('mimo-ca.nr',sp+'initialDownlinkBWP/pdsch-Config/setup/maxNrofCodeWordsScheduledByDCI',tech='NR'),
'phy-06':item('phy.carrier','spCellConfig/reconfigurationWithSync/spCellConfigCommon/downlinkConfigCommon/frequencyInfoDL/scs-SpecificCarrierList/[*]/subcarrierSpacing',tech='NR'),
'phy-07':item('phy.carrier',*['spCellConfig/reconfigurationWithSync/spCellConfigCommon/tdd-UL-DL-ConfigurationCommon/pattern1/'+x for x in ['dl-UL-TransmissionPeriodicity','nrofDownlinkSlots','nrofUplinkSlots','nrofDownlinkSymbols','nrofUplinkSymbols']],tech='NR'),
'phy-08':item('phy.reference',sp+'initialDownlinkBWP/pdsch-Config/setup/mcs-Table',tech='NR'),
'power-control-08':item('power-control.nr',sp+'uplinkConfig/initialUplinkBWP/pusch-Config/setup/pusch-PowerControl/p0-AlphaSets/[*]/p0',tech='NR'),
'rlc-pdcp-10':item('rlc-pdcp.nr',*['rlc-BearerToAddModList/[*]/rlc-Config/'+x+'/t-Reassembly' for x in ['am/dl-AM-RLC','um-Bi-Directional/dl-UM-RLC']],tech='NR'),
 'timers-rlf-07':item('timers-rlf.nr-scg','spCellConfig/rlf-TimersAndConstants/setup/t310',tech='NR')}
updates=[];proof=[]
for eid,(sub,tech,paths) in answers.items():
 refs=[]
 for suffix in paths:
  observed=[r for r in rows if r['system']==tech and (r['path']==suffix or r['path'].endswith('/'+suffix))]
  paths_found=sorted({r['path'] for r in observed}) or [(R if tech=='LTE' else '')+suffix]
  for path in paths_found:
   keys={r['param_key'] for r in observed if r['path']==path}
   key=next(iter(keys)) if len(keys)==1 else path
   refs.append(dict(param_key=key,path_prefix=path,technology=tech,discriminators={}))
   proof.append(dict(entry_id=eid,technology=tech,path=path,observed=bool(observed),n_occurrences=sum(int(r['n_occurrences']) for r in observed if r['path']==path)))
 category=eid.rsplit('-',1)[0]
 updates.append(dict(category_id=category,entry_id=eid,parameters=refs))
 seed['template_links']=[x for x in seed['template_links'] if x['entry_id']!=eid]
 seed['template_links'].append(dict(template_category_id=category,entry_id=eid,subcategory_id=sub,note='Chemin approuvé par utilisateur ; absence du projet conservée à zéro.'))
seed['template_updates']=updates
seed['template_unresolved']=[]
seed['status']='APPROVED' if not seed['unresolved'] else 'REVIEW_REQUIRED'
S.write_text(json.dumps(seed,ensure_ascii=False,indent=2)+'\n')
with (A/'template-paths.csv').open('w') as f:
 w=csv.DictWriter(f,fieldnames=list(proof[0]));w.writeheader();w.writerows(proof)
(A/'template-unmapped.csv').write_text('template_category_id,entry_id,label,existing_reason,proven_subcategories,question\n')
