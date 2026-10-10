from pathlib import Path

from app.kb import Kb

FIXTURES = Path(__file__).parent / "fixtures"

ADS = {"company": "Example Ads", "category": "advertising", "source": "disconnect"}


def test_lookup_walks_up_the_name():
    kb = Kb({"example.com": ADS}, {})
    expected = {"company": "Example Ads", "category": "advertising", "source": "list"}
    assert kb.lookup("example.com") == expected
    assert kb.lookup("a.b.example.com") == expected
    assert kb.lookup("notexample.com") is None
    assert kb.lookup("com") is None


def test_override_wins_at_the_same_level():
    kb = Kb({"example.com": ADS}, {"example.com": {"company": "Example", "category": "vendor"}})
    assert kb.lookup("x.example.com") == {"company": "Example", "category": "vendor", "source": "override"}


def test_override_wins_over_a_more_specific_kb_entry():
    kb = Kb({"ads.example.com": ADS}, {"example.com": {"company": "Example", "category": "vendor"}})
    assert kb.lookup("x.ads.example.com") == {"company": "Example", "category": "vendor", "source": "override"}
    assert kb.lookup("www.example.com")["source"] == "override"


def test_the_most_specific_override_wins_among_overrides():
    kb = Kb({}, {"apple.com": {"company": "Apple", "category": "vendor"},
                 "ca.iadsdk.apple.com": {"company": "Apple", "category": "advertising"}})
    assert kb.lookup("ca.iadsdk.apple.com")["category"] == "advertising"
    assert kb.lookup("gateway.apple.com")["category"] == "vendor"


def test_unexpected_category_becomes_unknown():
    kb = Kb({"example.com": {"company": "Example", "category": "spyware"}}, {})
    assert kb.lookup("example.com")["category"] == "unknown"


def test_company_domains_follow_overrides():
    kb = Kb({"a.example": ADS, "b.example": ADS, "x.c.example": ADS},
            {"b.example": {"company": "Other", "category": "content"}, "c.example": {"company": "Other", "category": "content"}})
    assert kb.company_domains("Example Ads") == {"a.example"}
    assert kb.company_domains("Other") == {"b.example", "c.example", "x.c.example"}  # as lookup() answers for each name
    assert kb.company_domains("Nobody") == set()
    assert ("x.c.example", "Other", "content", "override") in kb.entries()


def test_fixture_files_load():
    kb = Kb.load(FIXTURES / "kb.json", FIXTURES / "kb_overrides.json")
    assert kb.lookup("googleads.g.doubleclick.net")["company"] == "Google"
    assert kb.lookup("gateway.icloud.com") == {"company": "Apple", "category": "vendor", "source": "override"}


def test_missing_or_broken_files_mean_an_empty_kb(tmp_path):
    broken = tmp_path / "kb.json"
    broken.write_text("{ not json")
    kb = Kb.load(broken, tmp_path / "missing.json")
    assert len(kb) == 0
    assert kb.lookup("example.com") is None


def test_keys_are_normalized_on_load(tmp_path):
    path = tmp_path / "kb.json"
    path.write_text('{"domains": {"Example.COM.": {"company": "Example", "category": "content"}}}')
    assert Kb.load(path, tmp_path / "missing.json").lookup("www.example.com")["company"] == "Example"
