from scripts.audit_public_tree import PII_RULES, unapproved_email_matches


def test_mobile_rule_detects_standalone_number_but_not_sha256_substring() -> None:
    standalone = ("138" + "0013" + "8000").encode()
    digest = ("sha256:aa" + standalone.decode() + "dd").encode()

    assert PII_RULES["mainland_china_mobile"].search(standalone)
    assert not PII_RULES["mainland_china_mobile"].search(digest)


def test_only_explicit_public_author_email_is_exempt() -> None:
    public_author = b"jiaoyanglifly@gmail.com"
    private_address = b"private" + b"@" + b"example.com"
    matches = PII_RULES["email_address"].findall(
        public_author + b" " + private_address
    )

    assert unapproved_email_matches(matches) == [private_address]
