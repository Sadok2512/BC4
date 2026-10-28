from app.scripts.requeue_import_decoder_172_failures import is_decoder_172_failure


def test_only_matching_error_files_are_selected():
    assert is_decoder_172_failure({
        'status':'error',
        'error_msg':"unsupported operand type(s) for +=: 'float' and 'str'",
    })
    assert not is_decoder_172_failure({
        'status':'done',
        'error_msg':"unsupported operand type(s) for +=: 'float' and 'str'",
    })
    assert not is_decoder_172_failure({'status':'error','error_msg':'another failure'})
