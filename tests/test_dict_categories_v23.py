"""Approved IE suffix mapping and identifier exclusions, without reference fixtures."""
import csv,json
from pathlib import Path
import pytest
from app.dict.category_mapping import mapping_path,resolve_mapping,identifier_path_rule
from app.dict.enrich_v2 import enrich
ROOT=Path(__file__).resolve().parents[1]
SEED=json.loads((ROOT/'app/dict/config/categories_v23.json').read_text())

@pytest.mark.parametrize('message',['rrcConnectionReconfiguration','rrcConnectionReestablishment','rrcConnectionSetup'])
def test_message_wrapper_does_not_change_category(message):
    path=message+'/'+message+'-r8/radioResourceConfigDedicated/physicalConfigDedicated/antennaInfo/explicitValue/transmissionMode'
    assert resolve_mapping('LTE',path,{},SEED['maps'])['subcategory_id']=='mimo-ca.antennas'

def test_all_reviewed_test3_paths_are_classified_or_excluded():
    for r in csv.DictReader((ROOT/'audit/dict-v2.2/unmapped_test3.csv').open()):
        assert identifier_path_rule(r['path']) or resolve_mapping(r['technology'],r['path'],json.loads(r['discriminator']),SEED['maps']),r['path']

def test_no_message_duplicate_or_name_regex():
    identities=[(m['technology'],m['path_prefix'],json.dumps(m['discriminator'],sort_keys=True)) for m in SEED['maps']]
    assert len(set(identities))==len(identities)
    assert all(mapping_path(m['path_prefix'])==m['path_prefix'] for m in SEED['maps'])
    assert resolve_mapping('NR','TEST/unrelated/alpha',{},SEED['maps']) is None

@pytest.mark.parametrize('path',['TEST/measId-r12','TEST/scramblingID0','TEST/traceReference-r10/traceId','TEST/mnc/[1]','TEST/physCellId','TEST/interFreqExcludedCellList/[1]/start'])
def test_identifier_paths(path):
    assert identifier_path_rule(path)
    assert enrich(path,'RRCConnectionReconfiguration')['is_identifier']

@pytest.mark.parametrize('path',['TEST/logicalChannelGroup','TEST/offsetToCarrier','TEST/start','TEST/codebookSubsetRestriction/n2TxAntenna-tm4'])
def test_parameters_are_kept(path):
    assert identifier_path_rule(path) is None

def test_nr_sa_and_secondary_cell_group_same_rules():
    suffix='CellGroupConfig/spCellConfig/spCellConfigDedicated/uplinkConfig/initialUplinkBWP/pusch-Config/setup/pusch-PowerControl/p0-AlphaSets/[2]/p0'
    for wrapper in ['rrcSetup/rrcSetup/masterCellGroup/','rrcReconfiguration/rrcReconfiguration/secondaryCellGroup/']:
        assert resolve_mapping('NR',wrapper+suffix,{},SEED['maps'])['subcategory_id']=='power-control.nr'

def test_most_specific_rule_wins():
    p='systemInformationBlockType1/servingCellConfigCommon/uplinkConfigCommon/frequencyInfoUL/'
    assert resolve_mapping('NR',p+'p-Max',{},SEED['maps'])['subcategory_id']=='power-control.common'
    assert resolve_mapping('NR',p+'scs-SpecificCarrierList/[0]/carrierBandwidth',{},SEED['maps'])['subcategory_id']=='phy.carrier'


def test_mapping_path_cache_does_not_change_normalization():
    from app.dict.category_mapping import mapping_path
    mapping_path.cache_clear()
    paths=['TEST/root/measConfig/list/[0]/value','TEST/root/measConfig/list/[1]/value','TEST/root/measConfig2/value']
    for path in paths:
        assert mapping_path(path)==mapping_path.__wrapped__(path)
        assert mapping_path(path)==mapping_path.__wrapped__(path)
    assert mapping_path.cache_info().hits >= len(paths)
    assert mapping_path.cache_info().maxsize==8192
