from app.core.exiftool import normalize_tag, parse_tags


def test_parse_tags() -> None:
    record = {
        "IPTC:Keywords": ["summer", "beach"],
        "XMP-dc:Subject": ["family"],
        "XMP-lr:HierarchicalSubject": ["Places|USA|CA"],
    }
    tags = parse_tags(record)
    tag_names = {t.tag for t in tags}
    assert "summer" in tag_names
    assert "beach" in tag_names
    assert "family" in tag_names
    assert "Places|USA|CA" in tag_names


def test_normalize_tag_collapses_spaces() -> None:
    assert normalize_tag("  hello   world  ") == "hello world"


def test_parse_hierarchical_keeps_commas_inside_parentheses() -> None:
    record = {
        "XMP-lr:HierarchicalSubject": [
            "People|Baján Mária (Marika, keresztanyám), People|Baján Péter (Péter, Peti)"
        ],
    }
    tags = parse_tags(record)
    tag_names = {t.tag for t in tags}
    assert "People|Baján Mária (Marika, keresztanyám)" in tag_names
    assert "People|Baján Péter (Péter, Peti)" in tag_names
    assert "keresztanyám)" not in tag_names
