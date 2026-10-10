from app import state as state_module
from app.kb import Kb
from app.state import State, read_ai_seed
from app.summary import describe

KB = Kb(
    {"doubleclick.net": {"company": "Google", "category": "advertising"},
     "app-measurement.com": {"company": "Google", "category": "analytics"},
     "facebook.com": {"company": "Meta", "category": "social"}},
    {"apple.com": {"company": "Apple", "category": "vendor"}},
)
PHONE = "10.42.0.23"


def event(qname, ts=1000.0, ip=PHONE, qtype="A", name=None, blocked=False, reason=None):
    return {"ts": ts, "client_ip": ip, "client_name": name, "qname": qname, "qtype": qtype,
            "blocked": blocked, "block_reason": reason}


def hits(messages):
    return [m for m in messages if m["type"] == "hit"]


def test_first_event_creates_the_device_and_a_hit():
    state = State(KB)
    messages = state.ingest([event("ad.doubleclick.net", name="iPhone")])
    assert messages == [
        {"type": "device", "device_id": PHONE, "name": "iPhone", "persist": False},
        {"type": "hit", "device_id": PHONE, "domain": "ad.doubleclick.net", "company": "Google",
         "category": "advertising", "source": "list", "blocked": False, "block_reason": None, "ts": 1000.0},
    ]


def test_a_aaaa_https_burst_is_one_hit():
    state = State(KB)
    burst = [event("ad.doubleclick.net", 1000.00, qtype="A"), event("ad.doubleclick.net", 1000.01, qtype="AAAA"),
             event("AD.doubleclick.net.", 1000.02, qtype="HTTPS")]
    assert len(hits(state.ingest(burst))) == 1
    assert len(hits(state.ingest([event("ad.doubleclick.net", 1001.9)]))) == 0  # still inside the 2 s window
    assert len(hits(state.ingest([event("ad.doubleclick.net", 1002.1)]))) == 1  # the window does not slide
    assert len(hits(state.ingest([event("ad.doubleclick.net", 1002.2, ip="10.42.0.24")]))) == 1  # another device


def test_batches_move_onto_our_clock_and_keep_their_spacing():
    state = State(KB)
    found = hits(state.ingest([event("ad.doubleclick.net", 50.0), event("app-measurement.com", 50.25),
                               event("graph.facebook.com", 51.0)], now=2000.0))
    assert [h["ts"] for h in found] == [1999.0, 1999.25, 2000.0]
    assert state.ingest([], now=2000.0) == []


def test_phones_are_numbered_until_named():
    state = State(KB)
    first = state.ingest([event("apple.com")])[0]
    second = state.ingest([event("apple.com", ip="10.42.0.24")])[0]
    assert (first["name"], second["name"]) == ("Device 1", "Device 2")
    assert state.ingest([event("www.apple.com", 1010.0)]) != [] and state.devices[PHONE]["name"] == "Device 1"
    assert state.set_device("10.42.0.24", "Test iPhone B", None)["name"] == "Test iPhone B"
    assert state.set_device("10.42.0.24", "", None)["name"] == "Test iPhone B"  # an empty name changes nothing
    assert state.set_device("10.42.0.77", None, True) == {"type": "device", "device_id": "10.42.0.77",
                                                         "name": "Device 3", "persist": True}
    state.wipe()
    assert state.ingest([event("apple.com", ip="10.42.0.50")])[0]["name"] == "Device 1"


def test_plumbing_names_are_ignored():
    state = State(KB)
    noise = ["lb._dns-sd._udp.0.0.42.10.in-addr.arpa", "_dns.resolver.arpa", "printer.local", "localhost", ""]
    assert state.ingest([event(name) for name in noise]) == []
    assert state.devices == {}


def test_unknown_names_are_hits_and_get_queued_once():
    state = State(KB)
    messages = state.ingest([event("odd.example.io"), event("odd.example.io", 1005.0)])
    assert [(h["company"], h["category"], h["source"]) for h in hits(messages)] == [(None, "unknown", "unknown")] * 2
    assert state.take_pending(10) == ["odd.example.io"]
    state.ingest([event("odd.example.io", 1010.0)])
    assert state.take_pending(10) == []  # already asked


def test_ai_answers_upgrade_stored_hits_and_later_ones():
    state = State(KB)
    state.ingest([event("odd.example.io"), event("other.example.io")])
    names = state.take_pending(10)
    messages = state.apply_classified(names, {
        "odd.example.io": {"company": "Example Analytics", "category": "analytics", "confidence": 0.7},
        "other.example.io": {"company": None, "category": "nonsense", "confidence": "high"},
    })
    assert messages == [{"type": "classified", "domain": "odd.example.io", "company": "Example Analytics",
                         "category": "analytics", "source": "ai", "confidence": 0.7}]
    assert [(h["company"], h["source"]) for h in state.hits] == [("Example Analytics", "ai"), (None, "unknown")]
    later = hits(state.ingest([event("odd.example.io", 1010.0), event("other.example.io", 1010.0)]))
    assert [h["source"] for h in later] == ["ai", "unknown"]
    assert state.take_pending(10) == []


def test_database_answers_are_known_at_once_and_survive_a_wipe():
    state = State(KB)
    state.seed_ai({"odd.example.io": {"company": "Example Analytics", "category": "analytics", "confidence": 0.7}})
    for _ in range(2):
        hit = hits(state.ingest([event("odd.example.io")]))[0]
        assert (hit["company"], hit["source"]) == ("Example Analytics", "ai")
        assert state.take_pending(10) == []  # never sent to the AI again
        state.wipe()


def test_seen_by_persist_device():
    state = State(KB)
    state.ingest([event("odd.example.io"), event("other.example.io", ip="10.42.0.24")])
    assert not state.seen_by_persist_device("odd.example.io")
    state.set_device(PHONE, None, True)
    assert state.seen_by_persist_device("odd.example.io")
    assert not state.seen_by_persist_device("other.example.io")


def test_failed_ai_batch_goes_back_to_the_front_of_the_queue():
    state = State(KB)
    state.ingest([event("a.example.io"), event("b.example.io")])
    first = state.take_pending(1)
    state.requeue(first)
    assert state.take_pending(10) == ["a.example.io", "b.example.io"]


def test_blocking_a_company_expands_to_its_domains():
    state = State(KB)
    version = state.blocklist()["version"]
    assert state.set_blocked("Google", None, True) == {"type": "blocked", "companies": ["Google"], "domains": []}
    state.set_blocked(None, "Tracker.Example.COM.", True)
    blocklist = state.blocklist()
    assert blocklist["domains"] == ["app-measurement.com", "doubleclick.net", "tracker.example.com"]
    assert blocklist["version"] > version
    state.set_blocked("Google", None, False)
    assert state.blocklist()["domains"] == ["tracker.example.com"]


def test_blocking_a_company_covers_names_the_ai_assigned_to_it():
    state = State(KB)
    state.ingest([event("odd.example.io")])
    state.apply_classified(state.take_pending(10), {"odd.example.io": {"company": "Meta", "category": "social"}})
    state.set_blocked("Meta", None, True)
    assert state.blocklist()["domains"] == ["facebook.com", "odd.example.io"]


def test_blocked_events_stay_visible_as_hits():
    state = State(KB)
    messages = state.ingest([event("ad.doubleclick.net", blocked=True, reason="user"),
                             event("mask.icloud.com", blocked=True, reason="guard")])
    assert [(h["blocked"], h["block_reason"]) for h in hits(messages)] == [(True, "user"), (True, "guard")]


def test_dhcp_name_never_replaces_a_name_set_from_the_ui():
    state = State(KB)
    state.ingest([event("apple.com")])
    assert state.ingest([event("www.apple.com", name="iPhone")])[0]["name"] == "iPhone"  # learned late
    state.set_device(PHONE, "Test iPhone A", True)
    assert [m for m in state.ingest([event("x.apple.com", name="Other")]) if m["type"] == "device"] == []
    assert state.devices[PHONE] == {"device_id": PHONE, "name": "Test iPhone A", "persist": True}


def test_session_summary_counts_only_the_session():
    state = State(KB)
    state.set_device(PHONE, "Test iPhone A", None)
    state.ingest([event("early.doubleclick.net", 990.0)])
    assert state.refresh_summary(995.0) is None  # no session
    state.start_session(PHONE, "Demo Game", 1000.0)
    assert state.refresh_summary(1001.0) is None  # nothing new yet
    state.ingest([event("ad.doubleclick.net", 1001.0), event("app-measurement.com", 1002.0),
                  event("graph.facebook.com", 1003.0), event("ad.doubleclick.net", 1004.0),
                  event("ad.doubleclick.net", 1005.0, ip="10.42.0.99")])
    live = state.refresh_summary(1010.0)
    assert live["by"] == "template" and live["device_id"] == PHONE
    assert state.refresh_summary(1011.0) is None
    messages, stats = state.stop_session(1030.0)
    assert stats == {"device": "Test iPhone A", "label": "Demo Game", "seconds": 30,
                     "by_category": {"advertising": 2, "analytics": 1, "social": 1},
                     "top_companies": [["Google", 3], ["Meta", 1]], "blocked": 0, "hidden_attempts": 0}
    assert messages[0] == {"type": "session", "session": None}
    assert messages[1]["text"] == "In 30 seconds, Demo Game contacted 2 companies: 1 advertising (Google), 1 social (Meta)."
    assert state.session is None and state.summary is messages[1]
    assert state.last_session == {"device_id": PHONE, "label": "Demo Game", "started": 1000.0, "stopped": 1030.0}
    assert state.stop_session(1031.0) == ([], None)
    state.start_session(PHONE, "Next", 1040.0)
    assert state.last_session is None


def spoken(names, seconds=40, label="Demo Game", **extra):
    """The summary for a session in which PHONE looked up these names, classified by BIG_KB."""
    state = State(BIG_KB)
    state.start_session(PHONE, label, 1000.0)
    state.ingest([event(name, 1001.0 + i, **extra) for i, name in enumerate(names)])
    return describe(state.hits, state.session, 1000.0 + seconds)


BIG_KB = Kb({f"{company.lower()}.example": {"company": company, "category": category} for company, category in [
    ("Adco", "advertising"), ("Bidco", "advertising"), ("Clickco", "advertising"), ("Dspco", "advertising"),
    ("Exchangeco", "advertising"), ("Statco", "analytics"), ("Chatco", "social"), ("Printco", "fingerprinting"),
    ("Cdnco", "content"), ("Phoneco", "vendor")]}, {})


def test_summary_reads_well_aloud():
    assert spoken([]) == "No lookups from Demo Game in 40 seconds."
    assert spoken(["odd.example.io"], label=None) == "In 40 seconds, this phone contacted no company we know. 1 server could not be identified."
    assert spoken(["a.cdnco.example", "a.phoneco.example"], seconds=1) == (
        "In 1 second, Demo Game contacted 2 companies, none of them known for advertising or tracking.")
    assert spoken(["a.adco.example"]) == "In 40 seconds, Demo Game contacted 1 company: 1 advertising (Adco)."
    # most contacted first, three names at most, categories in a fixed order, the rest lumped together
    names = ["a.bidco.example", "b.bidco.example", "a.adco.example", "a.clickco.example", "a.dspco.example",
             "a.exchangeco.example", "a.statco.example", "a.chatco.example", "a.printco.example",
             "a.cdnco.example", "a.phoneco.example", "one.example.io", "two.example.io"]
    assert spoken(names, seconds=200) == (
        "In about 3 minutes, Demo Game contacted 10 companies: 5 advertising (Bidco, Adco, Clickco and 2 more), "
        "1 analytics (Statco), 1 social (Chatco), 1 fingerprinting (Printco), and 2 others. "
        "2 servers could not be identified.")
    for text in (spoken(names), spoken([])):
        assert "sent" not in text


def test_summary_counts_a_company_once_under_what_it_was_mostly_contacted_for():
    state = State(KB)  # Google: doubleclick.net is advertising, app-measurement.com is analytics
    state.start_session(PHONE, None, 1000.0)
    state.ingest([event("a.doubleclick.net", 1001.0), event("b.doubleclick.net", 1002.0), event("app-measurement.com", 1003.0)])
    assert describe(state.hits, state.session, 1010.0) == "In 10 seconds, this phone contacted 1 company: 1 advertising (Google)."


def test_guard_lookups_are_hidden_traffic_attempts_not_tracker_hits():
    state = State(KB)
    state.start_session(PHONE, "Demo Game", 1000.0)
    messages = state.ingest([
        event("_dns.resolver.arpa", 1001.0, qtype="SVCB", blocked=True, reason="guard"),  # plumbing name, kept as a guard hit
        event("dns.google", 1001.0, blocked=True, reason="guard"),
        event("mask.apple.com", 1001.0, blocked=True, reason="guard"),
        event("ad.doubleclick.net", 1002.0, blocked=True, reason="user"),
        event("app-measurement.com", 1003.0),
        event("lb._dns-sd._udp.0.0.42.10.in-addr.arpa", 1003.0, qtype="PTR")])  # plumbing, not a guard hit: dropped
    assert [(h["domain"], h["block_reason"]) for h in hits(messages)] == [
        ("_dns.resolver.arpa", "guard"), ("dns.google", "guard"), ("mask.apple.com", "guard"),
        ("ad.doubleclick.net", "user"), ("app-measurement.com", None)]
    assert state.take_pending(10) == []  # names we refused are never sent to the AI
    _, stats = state.stop_session(1010.0)
    assert stats["by_category"] == {"advertising": 1, "analytics": 1}  # Apple's relay host is not a "vendor contact"
    assert stats["top_companies"] == [["Google", 2]]
    assert (stats["blocked"], stats["hidden_attempts"]) == (1, 3)
    assert state.summary["text"] == ("In 10 seconds, Demo Game contacted 1 company: 1 advertising (Google). "
                                     "1 lookup was blocked. 3 hidden-traffic attempts were refused.")


def test_names_that_are_not_host_names_are_counted_and_dropped():
    state = State(KB)
    bad = ["x<script>alert(1)</script>.example.com", "a b.example.com", "caf\\195\\169.example.com", "a..b.example.com",
           "x" * 64 + ".example.com", ".".join(["a" * 60] * 5), "*.example.com", "evil\x00.example.com", "\x1b[31m.example.com"]
    assert state.ingest([event(name) for name in bad]) == []
    assert state.ingest([event("ad.doubleclick.net", ip="not-an-address")]) == []
    assert state.ingest([event("ad.doubleclick.net", ip="10.42.0.23<b>")]) == []
    assert state.health["malformed"] == len(bad) + 2
    assert state.devices == {} and not state.hits and not state.pending
    assert len(hits(state.ingest([event("ad.doubleclick.net"), event("ad.doubleclick.net", 1010.0, ip="fe80::1")]))) == 2
    state.wipe()
    assert state.health["malformed"] == len(bad) + 2  # a counter, not captured data: kept across a wipe


def test_free_text_from_outside_is_trimmed_to_printable():
    state = State(KB)
    device = state.ingest([event("apple.com", name="  Phone\x00\x1b[31m\n<b>" + "x" * 200)])[0]
    assert device["name"] == ("Phone[31m<b>" + "x" * 200)[:64]
    assert state.ingest([event("apple.com", ip="10.42.0.24", name="\x00\x07")])[0]["name"] == "Device 2"  # nothing printable left
    hit = hits(state.ingest([event("www.apple.com", 1010.0, blocked=True, reason="<i>")]))[0]
    assert (hit["blocked"], hit["block_reason"]) == (True, None)  # only "user" and "guard" are passed on
    state.ingest([event("odd.example.io")])
    state.apply_classified(state.take_pending(10), {"odd.example.io": {"company": "Evil\x00<script>" + "y" * 200, "category": "analytics"}})
    assert state.hits[-1]["company"] == ("Evil<script>" + "y" * 200)[:80]


def test_memory_bounds(monkeypatch):
    monkeypatch.setattr(state_module, "MAX_DEVICES", 3)
    monkeypatch.setattr(state_module, "MAX_AI_RESULTS", 5)
    state = State(KB)
    state.seed_ai({"seeded.example.io": {"company": "Example", "category": "analytics", "confidence": 0.9}})
    for i in range(6):
        state.ingest([event(f"n{i}.example.io", 1000.0 + 10 * i, ip=f"10.42.0.{i + 1}")])
    assert sorted(state.devices) == ["10.42.0.1", "10.42.0.2", "10.42.0.3"]  # later phones are ignored
    for i in range(20):
        state.ingest([event(f"m{i}.example.io", 2000.0 + 10 * i, ip="10.42.0.1")])
        state.take_pending(10)
    assert len(state.ai_results) <= 6 and "seeded.example.io" in state.ai_results  # the oldest answers go, the seed stays


def test_ai_seed_file(tmp_path):
    path = tmp_path / "ai_cache_seed.json"
    path.write_text('{"domains": {"Odd.Example.IO.": {"company": "Example Analytics", "category": "analytics", "confidence": 0.7},'
                    ' "junk.example.io": {"category": "nonsense"}, "worse.example.io": 5}}')
    assert read_ai_seed(path) == {"odd.example.io": {"company": "Example Analytics", "category": "analytics", "confidence": 0.7}}
    assert read_ai_seed(tmp_path / "missing.json") == {}
    path.write_text("[1, 2")
    assert read_ai_seed(path) == {}


def test_wipe_clears_everything_captured():
    state = State(KB)
    state.ingest([event("ad.doubleclick.net", name="iPhone"), event("odd.example.io")])
    state.set_blocked("Google", "x.example.com", True)
    state.start_session(PHONE, "Demo Game", 1000.0)
    state.refresh_summary(1001.0)
    version, generation = state.blocklist_version, state.generation
    assert state.wipe() == [{"type": "wiped"}, {"type": "blocked", "companies": [], "domains": []},
                            {"type": "session", "session": None}]
    snapshot = state.snapshot()
    assert (snapshot["devices"], snapshot["hits"], snapshot["session"], snapshot["summary"]) == ([], [], None, None)
    assert snapshot["blocked"] == {"companies": [], "domains": []}
    assert state.blocklist() == {"version": version + 1, "domains": []}
    assert state.generation == generation + 1
    assert not state.pending and not state.ai_results and not state.last_counted
    assert len(hits(state.ingest([event("ad.doubleclick.net")]))) == 1  # dedupe memory is gone too


def test_hit_history_is_bounded(monkeypatch):
    monkeypatch.setattr(state_module, "MAX_HITS", 10)
    state = State(KB)
    state.ingest([event(f"h{i}.doubleclick.net", 1000.0 + i) for i in range(100)])
    assert len(state.hits) == 10 and state.hits[-1]["domain"] == "h99.doubleclick.net"
    assert len(state.last_counted) <= 41
