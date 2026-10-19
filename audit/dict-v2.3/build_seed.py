"""Compile user-approved IE prefix rules. No regex/name-based categorization."""
import json
from pathlib import Path
from app.dict.category_mapping import mapping_path,resolve_mapping
old=json.loads(Path('app/dict/config/categories_v22.json').read_text())
new=[]
def add(tech,sub,*paths):
 for path in paths:new.append(dict(technology=tech,path_prefix=mapping_path(path),category_id=sub.split('.')[0],subcategory_id=sub,discriminator={},note='Classement utilisateur Test_3, R1 et table LTE/NR, 2026-10-19'))
def l(sub,*paths):add('LTE',sub,*paths)
def n(sub,*paths):add('NR',sub,*paths)
p='physicalConfigDedicated/';m='mac-MainConfig/explicitValue/'
l('mobility.mdt','loggedMeasurementConfiguration-r10/loggedMeasurementConfiguration-r10/absoluteTimeInfo-r10','loggedMeasurementConfiguration-r10/loggedMeasurementConfiguration-r10/loggingDuration-r10','loggedMeasurementConfiguration-r10/loggedMeasurementConfiguration-r10/loggingInterval-r10')
l('mobility.reports','measConfig/measIdToRemoveListExt-r12')
l('mac.timing',m+'stag-ToAddModList-r11/[*]/timeAlignmentTimerSTAG-r11',m+'stag-ToReleaseList-r11',m+'timeAlignmentTimerDedicated')
l('mac.bsr-phr',m+'phr-Config',m+'ul-SCH-Config/periodicBSR-Timer',m+'ul-SCH-Config/retxBSR-Timer')
l('mac.harq',m+'ul-SCH-Config/maxHARQ-Tx',m+'ul-SCH-Config/ttiBundling')
l('phy.csi',p+'cqi-ReportConfig',p+'cqi-ReportConfig-r10')
l('mimo-ca.antennas',p+'cqi-ReportConfig/cqi-ReportPeriodic/setup/ri-ConfigIndex',p+'cqi-ReportConfig-r10/cqi-ReportPeriodic-r10/setup/ri-ConfigIndex',p+'antennaInfo',p+'antennaInfo-r10')
l('power-control.dedicated',p+'uplinkPowerControlDedicated')
l('phy.reference',p+'pdsch-ConfigDedicated/p-a',p+'soundingRS-UL-ConfigDedicated',*(p+'pusch-ConfigDedicated/'+x for x in ['betaOffset-ACK-Index','betaOffset-CQI-Index','betaOffset-RI-Index']))
l('mac.sr',p+'schedulingRequestConfig')
l('mac.logical','srb-ToAddModList/[*]/logicalChannelConfig')
l('rlc-pdcp.bearers','srb-ToAddModList/[*]/rlc-Config')
l('rlc-pdcp.am-dl','srb-ToAddModList/[*]/rlc-Config/explicitValue/am/dl-AM-RLC')
l('rlc-pdcp.am-ul','srb-ToAddModList/[*]/rlc-Config/explicitValue/am/ul-AM-RLC')
l('access-barring.causes','rrcConnectionReestablishmentRequest/rrcConnectionReestablishmentRequest-r8/reestablishmentCause')
l('layering-idle.access','systemInformationBlockType1/cellSelectionInfo/q-RxLevMinOffset')
b='systemInformation/systemInformation-r8/sib-TypeAndInfo/[*]/'
l('access-barring.barring',b+'sib2/ac-BarringInfo')
l('phy.carrier',b+'sib2/mbsfn-SubframeConfigList')
l('layering-idle.inter',b+'sib5/interFreqCarrierFreqList/[*]/t-ReselectionEUTRA-SF',b+'sib5/interFreqCarrierFreqList/[*]/interFreqNeighCellList/[*]/q-OffsetCell')
n('mac.bsr-phr','mac-CellGroupConfig/bsr-Config','mac-CellGroupConfig/phr-Config')
n('mac.sr','mac-CellGroupConfig/schedulingRequestConfig/schedulingRequestToAddModList/[*]/sr-TransMax')
n('mac.harq','mac-CellGroupConfig/skipUplinkTxDynamic','physicalCellGroupConfig/pdsch-HARQ-ACK-Codebook')
n('mac.timing','mac-CellGroupConfig/tag-Config/tag-ToAddModList/[*]/timeAlignmentTimer')
r='rlc-BearerToAddModList/[*]/'
n('mac.logical',r+'mac-LogicalChannelConfig');n('rlc-pdcp.bearers',r+'rlc-Config')
n('rlc-pdcp.am-dl',r+'rlc-Config/am/dl-AM-RLC');n('rlc-pdcp.am-ul',r+'rlc-Config/am/ul-AM-RLC')
s='spCellConfigDedicated/';c=s+'csi-MeasConfig/setup/'
n('phy.csi',s+'csi-MeasConfig')
n('mimo-ca.nr',c+'csi-ReportConfigToAddModList/[*]/codebookConfig',c+'nzp-CSI-RS-ResourceToAddModList/[*]/resourceMapping/nrofPorts')
d=s+'initialDownlinkBWP/';pd=d+'pdsch-Config/setup/'
n('phy.pdcch',d+'pdcch-Config')
n('phy.reference',pd+'dmrs-DownlinkForPDSCH-MappingTypeA',pd+'dmrs-DownlinkForPDSCH-MappingTypeB',pd+'tci-StatesToAddModList')
n('mimo-ca.nr',pd+'maxNrofCodeWordsScheduledByDCI',s+'pdsch-ServingCellConfig/setup/maxMIMO-Layers')
n('phy.allocation',*(pd+x for x in ['pdsch-TimeDomainAllocationList','rbg-Size','resourceAllocation','prb-BundlingType']))
n('mac.harq',s+'pdsch-ServingCellConfig/setup/nrofHARQ-ProcessesForPDSCH')
u=s+'uplinkConfig/initialUplinkBWP/';pc=u+'pucch-Config/setup/';pu=u+'pusch-Config/setup/'
n('phy.reference',u+'pucch-Config',u+'srs-Config')
n('phy.allocation',pc+'dl-DataToUL-ACK',pu+'pusch-TimeDomainAllocationList',pu+'resourceAllocation')
n('power-control.nr',pc+'pucch-PowerControl',pu+'pusch-PowerControl',u+'srs-Config/setup/srs-ResourceSetToAddModList/[*]/alpha',u+'srs-Config/setup/srs-ResourceSetToAddModList/[*]/p0')
n('mac.sr',pc+'schedulingRequestResourceToAddModList')
n('mimo-ca.nr',*(pu+x for x in ['codebookSubset','maxRank','txConfig']))
n('phy.reference',*(pu+x for x in ['dmrs-UplinkForPUSCH-MappingTypeA','dmrs-UplinkForPUSCH-MappingTypeB','transformPrecoder','uci-OnPUSCH']))
n('access-barring.causes','rrcSetupRequest/rrcSetupRequest/establishmentCause')
b='systemInformationBlockType1/';sc=b+'servingCellConfigCommon/';dl=sc+'downlinkConfigCommon/';ul=sc+'uplinkConfigCommon/';ib=dl+'initialDownlinkBWP/';iu=ul+'initialUplinkBWP/'
n('access-barring.barring',b+'cellAccessRelatedInfo/plmn-IdentityInfoList/[*]/cellReservedForOperatorUse')
n('layering-idle.access',b+'cellSelectionInfo/q-RxLevMin')
n('layering-idle.paging',dl+'bcch-Config',dl+'pcch-Config',b+'si-SchedulingInfo')
n('phy.carrier',dl+'frequencyInfoDL',ul+'frequencyInfoUL',ib+'genericParameters',iu+'genericParameters',sc+'tdd-UL-DL-ConfigurationCommon')
n('phy.pdcch',ib+'pdcch-ConfigCommon','mib/pdcch-ConfigSIB1/controlResourceSetZero','mib/pdcch-ConfigSIB1/searchSpaceZero')
n('phy.allocation',ib+'pdsch-ConfigCommon/setup/pdsch-TimeDomainAllocationList',iu+'pusch-ConfigCommon/setup/pusch-TimeDomainAllocationList')
n('phy.reference',sc+'ssb-PeriodicityServingCell',sc+'ssb-PositionsInBurst',iu+'pucch-ConfigCommon/setup/pucch-GroupHopping',iu+'pucch-ConfigCommon/setup/pucch-ResourceCommon')
n('power-control.nr',sc+'ss-PBCH-BlockPower')
n('power-control.common',ul+'frequencyInfoUL/p-Max',iu+'pucch-ConfigCommon/setup/p0-nominal',iu+'pusch-ConfigCommon/setup/msg3-DeltaPreamble',iu+'pusch-ConfigCommon/setup/p0-NominalWithGrant')
n('phy.prach',iu+'rach-ConfigCommon')
n('power-control.random-access',iu+'rach-ConfigCommon/setup/rach-ConfigGeneric/powerRampingStep',iu+'rach-ConfigCommon/setup/rach-ConfigGeneric/preambleReceivedTargetPower')
n('mac.random-access',iu+'rach-ConfigCommon/setup/ra-ContentionResolutionTimer')
n('mac.timing',ul+'timeAlignmentTimerCommon')
n('timers-rlf.connection',*(b+'ue-TimersAndConstants/'+x for x in ['t300','t301','t319']))
n('timers-rlf.rlf',*(b+'ue-TimersAndConstants/'+x for x in ['t310','n310','n311','t311']))
# Retain existing approved rules unless explicitly superseded by the new table.
compiled={}
for row in old['maps']:
 row=dict(row,path_prefix=mapping_path(row['path_prefix']))
 if resolve_mapping(row['technology'],row['path_prefix'],row['discriminator'],new):continue
 key=(row['technology'],row['path_prefix'],json.dumps(row['discriminator'],sort_keys=True))
 if key in compiled and compiled[key]['subcategory_id']!=row['subcategory_id']:raise ValueError(('Conflicting existing rules',key))
 compiled[key]=row
for row in new:compiled[(row['technology'],row['path_prefix'],json.dumps(row['discriminator'],sort_keys=True))]=row
subs=[dict(id='phy.pdcch',category_id='phy',code='pdcch',label='PDCCH & CORESET',position=5),dict(id='phy.allocation',category_id='phy',code='allocation',label='Allocation temps-fréquence',position=6),dict(id='mobility.mdt',category_id='mobility',code='mdt',label='MDT (mesures loguées)',position=10)]
Path('app/dict/config/categories_v23.json').write_text(json.dumps(dict(status='APPROVED',subcategories=subs,maps=list(compiled.values())),ensure_ascii=False,indent=2)+'\n')
print('Compiled exact IE prefixes',len(compiled))
