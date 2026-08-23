from scripts.audit_public_tree import PII_RULES


def test_mobile_rule_detects_standalone_number_but_not_sha256_substring() -> None:
    standalone = ("138" + "0013" + "8000").encode()
    digest = ("sha256:aa" + standalone.decode() + "dd").encode()

    assert PII_RULES["mainland_china_mobile"].search(standalone)
    assert not PII_RULES["mainland_china_mobile"].search(digest)
