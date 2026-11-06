from app.signaling.service import contains_identity, contains_opaque


def test_structural_non_critical_extensions_are_not_identities():
    value = {
        "message": {
            "criticalExtensions": {
                "nonCriticalExtension": {
                    "nonCriticalExtension": {"logicalChannelGroup": 0},
                },
            },
        },
    }

    assert contains_identity(value) is False


def test_real_identity_inside_non_critical_extension_stays_masked():
    value = {
        "nonCriticalExtension": {
            "dedicatedInfoNAS": b"private",
        },
    }

    assert contains_identity(value) is True


def test_late_opaque_extension_stays_masked():
    assert contains_identity({"lateNonCriticalExtension": b"opaque"}) is True


def test_opaque_binary_content_is_detected_separately_from_identity():
    value = {
        "nonCriticalExtension": {
            "nr-SecondaryCellGroupConfig-r15": b"opaque",
        },
    }

    assert contains_identity(value) is False
    assert contains_opaque(value) is True
