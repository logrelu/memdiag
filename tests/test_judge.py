from memdiag.judge import DiskCache, FakeJudge, parse_json, same_family
from memdiag.prompt import Prompt

P = Prompt("ask", 1, "Is $x relevant?")
J = Prompt("facts", 1, "Extract from: $message")


def test_fake_judge_scripted_and_callable():
    judge = FakeJudge({"ask": "yes", "facts": lambda text: '{"facts": ["%s"]}' % text.split(": ")[1]})
    assert judge.ask(P, x="Denver").text == "yes"
    r = judge.ask(J, role="extractor", as_json=True, message="moved")
    assert r.data == {"facts": ["moved"]} and r.role == "extractor"
    assert judge.calls[0] == ("ask", "Is Denver relevant?")
    assert judge.usage.by_role["extractor"]["calls"] == 1


def test_bad_json_is_retried_once_then_gives_none():
    judge = FakeJudge({"facts": ["not json", 'Sure! ```{"facts": []}```']})
    r = judge.ask(J, as_json=True, message="m")
    assert r.data == {"facts": []} and len(judge.calls) == 2
    assert "not a valid JSON object" in judge.calls[1][1]
    judge = FakeJudge({"facts": ["nope", "still nope"]})
    assert judge.ask(J, as_json=True, message="m").data is None


def test_cache_hit_makes_zero_calls(tmp_path):
    cache = DiskCache(tmp_path)
    first = FakeJudge({"facts": '{"facts": ["a"]}'}, cache=cache)
    assert first.ask(J, as_json=True, message="m").cached is False
    second = FakeJudge({"facts": "unused"}, cache=cache)
    r = second.ask(J, as_json=True, message="m")
    assert r.cached and r.data == {"facts": ["a"]} and second.calls == []
    assert second.usage.by_role["facts"]["cached"] == 1


def test_cache_misses_on_new_version_model_or_text(tmp_path):
    cache = DiskCache(tmp_path)
    FakeJudge({"facts": '{"a": 1}'}, cache=cache).ask(J, as_json=True, message="m")
    for judge, prompt, msg in [
        (FakeJudge({"facts": '{"a": 2}'}, cache=cache), Prompt("facts", 2, J.template), "m"),
        (FakeJudge({"facts": '{"a": 2}'}, model="other", cache=cache), J, "m"),
        (FakeJudge({"facts": '{"a": 2}'}, cache=cache), J, "different"),
    ]:
        assert judge.ask(prompt, as_json=True, message=msg).cached is False


def test_failed_parse_is_not_cached(tmp_path):
    cache = DiskCache(tmp_path)
    FakeJudge({"facts": ["bad", "bad"]}, cache=cache).ask(J, as_json=True, message="m")
    assert list(tmp_path.iterdir()) == []


def test_parse_json_and_families():
    assert parse_json('Here: {"a": [1]} done') == {"a": [1]}
    assert parse_json("[1, 2]") is None
    assert same_family("qwen2.5:7b", "Qwen2.5-72B-Instruct")
    assert not same_family("qwen2.5:7b", "llama3.1:8b")
    assert not same_family("my-model", "my-model")  # unknown family: no claim either way


def test_parse_json_review_cases():
    assert parse_json('{"a":1} then {"b":2}') == {"a": 1}
    assert parse_json('{"a":1}\nnote {x}') == {"a": 1}
    assert parse_json('[{"a":1}]') is None  # an array is not the object we asked for
    assert parse_json(None) is None


def test_corrupt_cache_entries_are_misses(tmp_path):
    cache = DiskCache(tmp_path)
    key = DiskCache.key("fake", "facts", 1, "Extract from: m", True)
    for bad in (b"\xff\xfe not utf8", b"[1]", b'{"text": "x"}', b"{not json"):
        (tmp_path / f"{key}.json").write_bytes(bad)
        r = FakeJudge({"facts": '{"ok": 1}'}, cache=cache).ask(J, as_json=True, message="m")
        assert r.cached is False and r.data == {"ok": 1}


def test_cache_hits_count_no_tokens(tmp_path):
    from memdiag.judge import Judge

    class Tokened(Judge):
        model = "t"

        def _complete(self, text, as_json, prompt_id):
            return "yes", {"prompt_tokens": 10, "completion_tokens": 2}

    cache = DiskCache(tmp_path)
    judge = Tokened(cache=cache)
    judge.ask(P, x="a")
    hit = judge.ask(P, x="a")
    assert hit.cached and (hit.prompt_tokens, hit.completion_tokens) == (0, 0)
    u = judge.usage.by_role["ask"]
    assert (u["calls"], u["cached"], u["prompt_tokens"], u["completion_tokens"]) == (2, 1, 10, 2)
