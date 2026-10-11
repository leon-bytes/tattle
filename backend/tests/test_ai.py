"""backend/app/ai.py without a model server: what it does with the model's text, and that it gives
up cleanly. The model's own answers are tried by hand with tools/try_ai.py."""
import asyncio
import time

import pytest

from app import ai, labels

STATS = {"device": "Test iPhone A", "label": "Demo Game", "seconds": 119,
         "by_category": {"advertising": 58, "analytics": 11, "vendor": 13, "unknown": 14},
         "top_companies": [["Google", 21], ["Apple", 15], ["AppLovin", 15]], "blocked": 0, "hidden_attempts": 4}


@pytest.fixture
def model(monkeypatch):
    """Stand in for the model server: `model.says` is its next answer, `model.asked` what it was sent."""
    class Model:
        says = ""
        asked: list = []

    async def call(messages, max_tokens, timeout=ai.TIMEOUT_S):
        Model.asked.append(messages)
        return Model.says
    Model.asked = []
    monkeypatch.setattr(ai, "_call", call)
    monkeypatch.setattr(ai, "_seed", None)  # read the seed fixture afresh
    return Model


def test_without_a_model_server_every_function_returns_none_and_never_raises():
    async def all_four():
        return [await ai.classify_domains(["odd.example.io"]), await ai.summarize(dict(STATS)),
                await ai.label_check({"app": "Demo Game"}, dict(STATS)),
                await ai.explain_company("Example Ads", "advertising", ["ads.example.com"]),
                await ai.classify_domains(None), await ai.summarize(None), await ai.label_check(None, None),
                await ai.explain_company(None, None, None)]
    assert asyncio.run(all_four()) == [None] * 8


def test_a_model_server_that_hangs_costs_no_more_than_the_time_limit(monkeypatch):
    async def hang(messages, max_tokens, timeout):
        await asyncio.sleep(30)
    monkeypatch.setattr(ai, "_chat", hang)
    monkeypatch.setattr(ai, "TIMEOUT_S", 0.3)
    started = time.monotonic()
    assert asyncio.run(ai._call([], 10, timeout=0.3)) is None
    assert asyncio.run(ai.classify_domains([f"n{i}.example.io" for i in range(25)])) is None  # three chunks, one limit
    assert time.monotonic() - started < 2


def test_text_that_claims_data_was_sent_is_cut_out():
    finish = ai._finish_text
    assert finish("The app contacted x.example.com. It sends your location to advertisers. It is an ad company.", 500) == \
        "The app contacted x.example.com. It is an ad company."
    assert finish("This app sent data to Google.", 500) is None
    assert finish("Example is an ad company. It tracks you across apps.", 500) is None  # nothing left says "contacted"
    # the fact survives, the guess that crossed the line does not
    assert finish("Mixpanel is an analytics company. The app contacted api.mixpanel.com, most likely its server "
                  "for sending usage data.", 500) == "Mixpanel is an analytics company. The app contacted api.mixpanel.com."
    # the title of the label's section is not a claim
    verdict = 'The label lists nothing under "Data Used to Track You", yet the app contacted Google: worth a closer look.'
    assert finish(verdict, 400) == verdict


def test_text_is_whole_english_sentences_without_afterthoughts():
    finish = ai._finish_text
    assert finish("Apple makes the iPhone. The phone contacted time.apple.com, most likely for the clock and 广告服务。", 500) is None
    assert finish("Apple makes the iPhone. The phone contacted time.apple.com. 这是苹果。", 500) == \
        "Apple makes the iPhone. The phone contacted time.apple.com."
    assert finish("The app contacted Google.\n\n--- This sentence is 4 words long.", 500) == "The app contacted Google."
    assert finish("The app contacted Google. It also contacted a server that is prob", 500) == "The app contacted Google."
    assert finish('"The app contacted Google."', 500) == "The app contacted Google."
    assert finish("A" * 300 + ". The app contacted b.example.com. " + "C" * 300 + ".", 500) == "A" * 300 + ". The app contacted b.example.com."
    assert finish("", 500) is None and finish(None, 500) is None


def test_classify_reads_one_line_per_name(model):
    names = ["api.word-game.example", "ads.example.net", "x.example.org", "cn.example.io", "seeded.example.io", "left-out.example.io"]
    model.says = ("1|Word Game|vendor|0.6\n2 | - | ad networks | 0.9\nnot a line\n3|-|unknown|0.9\n"
                  "4|字节跳动|social|0.9\n9|Nobody|vendor|0.5\n1|Twice|content|0.1\n5|Cut off|ven")
    result = asyncio.run(ai.classify_domains(names + ["API.Word-Game.example."]))
    assert result == {
        "seeded.example.io": {"company": "Example Seed", "category": "analytics", "confidence": 0.9},  # from the seed file
        "api.word-game.example": {"company": "Word Game", "category": "vendor", "confidence": 0.6},
        "ads.example.net": {"company": None, "category": "advertising", "confidence": 0.9},
        "x.example.org": {"company": None, "category": "unknown", "confidence": 0.3},
        "cn.example.io": {"company": None, "category": "social", "confidence": 0.9},  # a name our font cannot show
    }
    [messages] = model.asked  # one call; the seeded name was not sent
    assert messages[1]["content"] == "1. api.word-game.example\n2. ads.example.net\n3. x.example.org\n4. cn.example.io\n5. left-out.example.io"
    model.says = "Sorry, I cannot help with that."
    assert asyncio.run(ai.classify_domains(["odd.example.io"])) is None


def test_summary_keeps_only_numbers_it_was_given(model):
    model.says = "Demo Game contacted mostly advertising companies: 58 of its 96 lookups (60%) went to ad servers, led by Google."
    assert asyncio.run(ai.summarize(dict(STATS))) == model.says
    assert "advertising 58 (60%)" in model.asked[0][1]["content"]  # shares are worked out for the model
    assert "vendor" not in model.asked[0][1]["content"]
    model.says = "Demo Game contacted mostly advertising companies: 57 of its 96 lookups (59%) went to ad servers."
    assert asyncio.run(ai.summarize(dict(STATS))) is None
    model.asked.clear()
    assert asyncio.run(ai.summarize({**STATS, "by_category": {}, "top_companies": []})) is None
    assert model.asked == []  # nothing to name: the model is not asked


@pytest.mark.parametrize("label", [
    {"data_used_to_track_you": [], "data_not_collected": False},
    {"data_used_to_track_you": ["Identifiers"], "data_not_collected": False},
    {"data_used_to_track_you": [], "data_not_collected": True},
    {},
])
@pytest.mark.parametrize("by_category", [{"advertising": 3, "vendor": 9}, {"analytics": 2}, {"vendor": 9}, {}])
def test_label_finding_follows_the_backend_rules(label, by_category):
    """ai.py tells the model which way the verdict goes, so it has to agree with labels.verdict."""
    seen = {"advertising_companies": 1 if by_category.get("advertising") else 0,
            "tracking_companies": 1 if any(by_category.get(c) for c in labels.TRACKING) else 0}
    level, _ = labels.verdict(label, seen)
    facts = ai._label_facts(label, {**STATS, "by_category": by_category})
    assert ("does not match" in facts) == (level == "mismatch")


def test_explain_tells_apple_apart_from_an_app(model):
    model.says = "Apple makes the iPhone. The phone contacted time.apple.com, most likely for the clock."
    assert asyncio.run(ai.explain_company("Apple", "vendor", ["time.apple.com"])) == model.says
    assert "the phone's own housekeeping" in model.asked[-1][1]["content"]
    asyncio.run(ai.explain_company("Word Game", "vendor", ["api.word-game.example"]))
    assert "housekeeping" not in model.asked[-1][1]["content"] and "api.word-game.example" in model.asked[-1][1]["content"]
    asyncio.run(ai.explain_company("Example Ads", "nonsense", [f"h{i}.example.com" for i in range(40)]))
    assert model.asked[-1][1]["content"].count(".example.com") == ai.MAX_EXPLAIN_HOSTS


@pytest.fixture
def server():
    """A stand-in model server on a loopback port. `server.mode` says how it treats the next request."""
    import http.server
    import json
    import threading

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            box.connections.add(self.client_address)
            mode, box.mode = box.mode, "ok"
            if mode == "hang":
                time.sleep(1.5)
                return
            body = json.dumps({"choices": [{"message": {"content": "1|Example|vendor|0.6"}, "finish_reason": "stop"}]}).encode()
            self.send_response(404 if mode == "missing" else 200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            if mode == "drop":  # answers, then closes without saying so: the client finds out at its next request
                self.close_connection = True

        def log_message(self, *args):
            pass

    box = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    box.daemon_threads = True
    box.connections, box.mode = set(), "ok"
    box.url = f"http://127.0.0.1:{box.server_address[1]}/v1/chat/completions"
    threading.Thread(target=box.serve_forever, daemon=True).start()
    ai._idle.clear()
    yield box
    box.shutdown()
    box.server_close()
    ai._idle.clear()


def test_calls_share_one_connection_and_survive_its_loss(server):
    post = lambda timeout=2.0: ai._post_sync(server.url, {"Content-Type": "application/json"}, {"model": "m"}, timeout)
    for _ in range(3):
        assert post()["choices"][0]["message"]["content"] == "1|Example|vendor|0.6"
    assert len(server.connections) == 1  # opening a connection through the tunnel is the slow part
    server.mode = "drop"
    post()
    assert post()["choices"]  # the kept connection was dead: one more try on a new one
    assert len(server.connections) == 2
    server.mode = "missing"
    with pytest.raises(RuntimeError, match="404"):
        post()
    server.mode = "hang"
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        post(timeout=0.4)
    assert time.monotonic() - started < 1.0  # a timeout is final: no second try
    assert post()["choices"]
