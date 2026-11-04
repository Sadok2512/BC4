from app.signaling.service import radio_transition_attrs


def test_hoa_and_hos_use_certified_hoa_source_and_target_fields():
    detail = dict(hoa_hoa_type=3, hoa_pci=196, hoa_ch_number=1675,
                  hoa_att_pci=385, hoa_att_ch=1300)
    for code in ('HOA', 'HOS'):
        subtype, attrs = radio_transition_attrs(code, detail)
        assert subtype is None
        assert attrs == {
            'ho_type': 3,
            'source_pci': 196, 'source_earfcn': 1675,
            'target_pci': 385, 'target_earfcn': 1300,
            'pci': 385, 'earfcn': 1300,
            'target_cell': {'pci': 385, 'earfcn': 1300},
        }


def test_pscell_change_keeps_added_and_removed_identity():
    subtype, attrs = radio_transition_attrs('SCELLMOD', scg={
        'subtype': 'PSCELL_CHANGE',
        'added_pci': 534, 'added_earfcn': 643392,
        'removed_pci': 889, 'removed_earfcn': 643392,
    })
    assert subtype == 'PSCELL_CHANGE'
    assert attrs['source_pci'] == attrs['removed_pci'] == 889
    assert attrs['target_pci'] == attrs['added_pci'] == attrs['pci'] == 534
    assert attrs['target_earfcn'] == attrs['earfcn'] == 643392


def test_scg_add_and_release_use_only_the_present_group():
    _, added = radio_transition_attrs('SCELLMOD', scg={
        'subtype': 'SCG_ADD', 'added_pci': 722, 'added_earfcn': 643392,
    })
    _, removed = radio_transition_attrs('SCELLMOD', scg={
        'subtype': 'SCG_RELEASE', 'removed_pci': 722,
        'removed_earfcn': 643392,
    })
    assert added['target_cell'] == {'pci': 722, 'earfcn': 643392}
    assert removed['target_cell'] == {'pci': 722, 'earfcn': 643392}
    assert 'removed_pci' not in added
    assert 'added_pci' not in removed
