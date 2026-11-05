import json
import urllib.error

import pytest

from notebooklm_lab import channels as ch, cli, inbox as ib

CID = "UC" + "a" * 22
CID2 = "UC" + "b" * 22


def feed(title, videos):
    """videos: [(id, title, published)] newest first."""
    entries = "".join(
        f"<entry><id>yt:video:{i}</id><yt:videoId>{i}</yt:videoId><title>{t}</title><published>{d}</published></entry>"
        for i, t, d in videos
    )
    return (f"<?xml version='1.0'?><feed xmlns:yt='http://www.youtube.com/xml/schemas/2015' xmlns='http://www.w3.org/2005/Atom'>"
            f"<title>{title}</title>{entries}</feed>")


def page(cid):
    return f'<html><link rel="canonical" href="https://www.youtube.com/channel/{cid}"><script>"channelId":"UC{"z" * 22}"</script></html>'


class Web:
    """Fake YouTube: pages by URL, feeds by channel id; can fail N times first."""

    def __init__(self):
        self.pages, self.feeds, self.fail, self.calls = {}, {}, {}, []

    def __call__(self, url):
        self.calls.append(url)
        if "feeds/videos.xml" in url:
            cid = url.split("channel_id=")[1]
            if self.fail.get(cid, 0) > 0:
                self.fail[cid] -= 1
                raise ch.NetworkError("HTTP 500 من www.youtube.com", 500)
            if cid not in self.feeds:
                raise ch.NetworkError("HTTP 404 من www.youtube.com", 404)
            return self.feeds[cid]
        if url not in self.pages:
            raise ch.NetworkError("HTTP 404 من www.youtube.com", 404)
        return self.pages[url]


def V(i, n=None):
    return (f"vid{i:03d}xxxx", n or f"عنوان {i}", f"2026-11-{i:02d}T10:00:00+00:00")


@pytest.fixture
def web(monkeypatch):
    w = Web()
    monkeypatch.setattr(ch, "http_get", w)
    monkeypatch.setattr(ch.time, "sleep", lambda s: None)
    monkeypatch.delenv("NOTEBOOKLM_LAB_CHANNELS_AUTO", raising=False)
    return w


NOSLEEP = dict(sleep=lambda s: None)


# ------------------------------------------------------------------ parsing what the user types
@pytest.mark.parametrize("text,cid,url", [
    (CID, CID, None),
    (f"https://www.youtube.com/channel/{CID}/videos", CID, None),
    (f"youtube.com/channel/{CID}", CID, None),
    ("@NASA", None, "https://www.youtube.com/@NASA"),
    ("https://www.youtube.com/@NASA/videos?x=1", None, "https://www.youtube.com/@NASA"),
    ("https://m.youtube.com/@NASA", None, "https://www.youtube.com/@NASA"),
    ("https://www.youtube.com/c/SomeName", None, "https://www.youtube.com/c/SomeName"),
    ("https://www.youtube.com/user/old", None, "https://www.youtube.com/user/old"),
    ("@%D9%82%D9%86%D8%A7%D8%A9", None, "https://www.youtube.com/@%D9%82%D9%86%D8%A7%D8%A9"),
])
def test_parse_ref_forms(text, cid, url):
    r = ch.parse_ref(text)
    assert r.channel_id == cid and r.page_url == (url if url else None)


def test_parse_ref_arabic_handle_is_percent_encoded():
    r = ch.parse_ref("@قناة_عربية")
    assert r.handle == "@قناة_عربية" and "%D9%82" in r.page_url and r.page_url.startswith("https://www.youtube.com/@")


@pytest.mark.parametrize("bad", ["", "  ", "https://www.youtube.com/watch?v=abc", "https://youtu.be/abc", "https://example.com/@x", "just words", "https://www.youtube.com/playlist?list=PL1"])
def test_parse_ref_rejects(bad):
    with pytest.raises(ch.ChannelError):
        ch.parse_ref(bad)


def test_extract_channel_id_prefers_the_pages_own_identity():
    assert ch.extract_channel_id(page(CID)) == CID  # canonical beats the unrelated channelId in the same page
    assert ch.extract_channel_id(f'<meta itemprop="identifier" content="{CID}">') == CID
    assert ch.extract_channel_id(f'"externalId":"{CID2}" "channelId":"{CID}"') == CID2
    assert ch.extract_channel_id("<html>nothing</html>") is None


def test_resolve_handle_via_page_and_errors(web):
    web.pages["https://www.youtube.com/@NASA"] = page(CID)
    assert ch.resolve(ch.parse_ref("@NASA")) == CID
    assert ch.resolve(ch.parse_ref(CID)) == CID and len(web.calls) == 1  # an id needs no network
    web.pages["https://www.youtube.com/@odd"] = "<html></html>"
    with pytest.raises(ch.ChannelError, match="معرّف"):
        ch.resolve(ch.parse_ref("@odd"))
    with pytest.raises(ch.ChannelError, match="لم أجد قناة") as ei:
        ch.resolve(ch.parse_ref("@missing"))
    assert not isinstance(ei.value, ch.NetworkError)


# ------------------------------------------------------------------ feed
def test_parse_feed_and_bad_input():
    title, vids = ch.parse_feed(feed("قناتي", [V(2, "ثانٍ\n  مع  مسافات"), V(1)]))
    assert title == "قناتي" and [v.id for v in vids] == ["vid002xxxx", "vid001xxxx"]
    assert vids[0].title == "ثانٍ مع مسافات" and vids[0].url == "https://www.youtube.com/watch?v=vid002xxxx"
    _t, vids2 = ch.parse_feed(feed("x", [("bad id!", "t", "d"), V(3)]))
    assert [v.id for v in vids2] == ["vid003xxxx"]
    with pytest.raises(ch.ChannelError):
        ch.parse_feed("<feed><unclosed>")


def test_fetch_feed_retries_flaky_youtube_then_gives_up(web):
    web.feeds[CID] = feed("T", [V(1)])
    web.fail[CID] = 2
    slept = []
    assert ch.fetch_feed(CID, sleep=slept.append)[0] == "T" and slept == [2.0, 4.0]
    web.fail[CID] = 5
    with pytest.raises(ch.NetworkError):
        ch.fetch_feed(CID, sleep=lambda s: None)


def test_http_get_maps_errors_and_caps_size(monkeypatch):
    def http_err(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, None)

    monkeypatch.setattr(ch.urllib.request, "urlopen", http_err)
    with pytest.raises(ch.NetworkError) as ei:
        ch.http_get("https://www.youtube.com/@x")
    assert ei.value.status == 404

    def url_err(req, timeout=None):
        raise urllib.error.URLError("dns")

    monkeypatch.setattr(ch.urllib.request, "urlopen", url_err)
    with pytest.raises(ch.NetworkError, match="تعذّر"):
        ch.http_get("https://www.youtube.com/@x")

    class Big:
        def __enter__(self): return self
        def __exit__(self, *a): return None
        def read(self, n): return b"x" * n

    monkeypatch.setattr(ch.urllib.request, "urlopen", lambda req, timeout=None: Big())
    with pytest.raises(ch.NetworkError, match="أكبر"):
        ch.http_get("https://www.youtube.com/@x")


# ------------------------------------------------------------------ add / list / remove
def test_add_marks_existing_videos_seen_and_stores_handle(web, tmp_path):
    web.pages["https://www.youtube.com/@NASA"] = page(CID)
    web.feeds[CID] = feed("NASA", [V(3), V(2), V(1)])
    out = []
    assert ch.add("@NASA", tmp_path, say=out.append, **NOSLEEP) == 0
    st = ch.load(tmp_path)["channels"][CID]
    assert st["title"] == "NASA" and st["handle"] == "@NASA" and len(st["seen"]) == 3 and "أضيفت" in out[0].replace("أُضيفت", "أضيفت")
    assert ch.add("@NASA", tmp_path, say=out.append, **NOSLEEP) == 0 and "مسبقًا" in out[-1]
    assert not (tmp_path / "inbox.txt").exists()  # adding never touches the inbox


def test_add_with_backfill_queues_latest_on_first_check(web, tmp_path):
    web.feeds[CID] = feed("NASA", [V(3), V(2), V(1)])
    ch.add(CID, tmp_path, backfill=2, say=lambda m: None, **NOSLEEP)
    assert len(ch.load(tmp_path)["channels"][CID]["seen"]) == 1
    code, rep = ch.check(tmp_path, say=lambda m: None, sleep=lambda s: None)
    assert code == 0 and [v.id for _t, v in rep.added] == ["vid003xxxx", "vid002xxxx"]
    lines = [l for l in (tmp_path / "inbox.txt").read_text(encoding="utf-8").splitlines() if l.startswith("http")]
    assert [l.split()[0].rsplit("=", 1)[1] for l in lines] == ["vid002xxxx", "vid003xxxx"]  # oldest first


def test_add_errors_have_the_right_exit_codes(web, tmp_path):
    out = []
    assert ch.add("https://www.youtube.com/watch?v=abc", tmp_path, say=out.append) == 2
    assert ch.add("@nobody", tmp_path, say=out.append) == 2 and "لم أجد قناة" in out[-1]
    web.pages["https://www.youtube.com/@x"] = page(CID)
    web.feeds[CID] = "<<not xml"
    assert ch.add("@x", tmp_path, say=out.append, **NOSLEEP) == 2
    assert ch.load(tmp_path)["channels"] == {}


def test_add_when_feed_is_down_follows_anyway_and_first_check_initialises(web, tmp_path):
    web.pages["https://www.youtube.com/@Big"] = page(CID)
    web.fail[CID] = 99
    out = []
    assert ch.add("@Big", tmp_path, say=out.append, **NOSLEEP) == 0 and any("مؤقتًا" in m for m in out)
    assert ch.load(tmp_path)["channels"][CID]["pending_init"] is True
    code, rep = ch.check(tmp_path, say=out.append, sleep=lambda s: None)  # still down
    assert code == 4 and rep.failed == 1
    web.fail[CID] = 0
    web.feeds[CID] = feed("Big Channel", [V(2), V(1)])
    code, rep = ch.check(tmp_path, say=out.append, sleep=lambda s: None)
    assert code == 0 and rep.added == [] and not (tmp_path / "inbox.txt").exists()  # old videos are NOT flooded in
    c = ch.load(tmp_path)["channels"][CID]
    assert "pending_init" not in c and c["title"] == "Big Channel" and len(c["seen"]) == 2
    web.feeds[CID] = feed("Big Channel", [V(3), V(2), V(1)])
    assert [v.id for _t, v in ch.check(tmp_path, say=out.append, sleep=lambda s: None)[1].added] == ["vid003xxxx"]


def test_list_and_remove_by_handle_id_title(web, tmp_path):
    assert "لا توجد قنوات" in ch.list_text(tmp_path)
    web.pages["https://www.youtube.com/@NASA"] = page(CID)
    web.feeds[CID] = feed("NASA Official", [V(1)])
    web.feeds[CID2] = feed("NASA Kids", [V(1)])
    ch.add("@NASA", tmp_path, say=lambda m: None, **NOSLEEP)
    ch.add(CID2, tmp_path, say=lambda m: None, **NOSLEEP)
    text = ch.list_text(tmp_path)
    assert "NASA Official" in text and "@NASA" in text and CID2 in text and "لم تُفحص بعد" in text
    out = []
    assert ch.remove("nasa", tmp_path, say=out.append) == 2 and "أكثر من قناة" in "\n".join(out)  # ambiguous title
    assert ch.remove("zzzz", tmp_path, say=out.append) == 2
    assert ch.remove("https://www.youtube.com/@nasa", tmp_path, say=out.append) == 0  # handle match, case-insensitive
    assert list(ch.load(tmp_path)["channels"]) == [CID2]
    assert ch.remove(CID2, tmp_path, say=out.append) == 0 and ch.load(tmp_path)["channels"] == {}
    assert ch.remove("kids", tmp_path, say=out.append) == 2


# ------------------------------------------------------------------ check
def _follow(web, tmp_path, vids=(V(1),), title="القناة", cid=CID):
    web.feeds[cid] = feed(title, list(vids))
    ch.add(cid, tmp_path, say=lambda m: None, **NOSLEEP)


def _check(tmp_path, **kw):
    out = []
    code, rep = ch.check(tmp_path, say=out.append, sleep=lambda s: None, **kw)
    return code, rep, "\n".join(out)


def _inbox_links(tmp_path):
    return [l.split()[0] for l in (tmp_path / "inbox.txt").read_text(encoding="utf-8").splitlines() if l.startswith("http")]


def test_check_appends_new_links_with_comment_and_never_twice(web, tmp_path):
    _follow(web, tmp_path)
    assert _check(tmp_path)[1].added == [] and not (tmp_path / "inbox.txt").exists()
    web.feeds[CID] = feed("القناة", [V(3, "فيديو # جديد"), V(2), V(1)])
    code, rep, _ = _check(tmp_path)
    assert code == 0 and len(rep.added) == 2
    text = (tmp_path / "inbox.txt").read_text(encoding="utf-8")
    assert "# القناة: فيديو # جديد" in text and text.endswith("\n")
    assert _inbox_links(tmp_path) == ["https://www.youtube.com/watch?v=vid002xxxx", "https://www.youtube.com/watch?v=vid003xxxx"]
    # the inbox parser understands these lines (comment after the link is ignored; each link is one entry)
    entries, _dups = ib.read_inbox(tmp_path / "inbox.txt")
    assert [e.key for e in entries] == ["youtube:vid002xxxx", "youtube:vid003xxxx"]
    assert _check(tmp_path)[1].added == [] and len(_inbox_links(tmp_path)) == 2  # second check: nothing again


def test_check_keeps_existing_inbox_text_and_adds_newline(web, tmp_path):
    _follow(web, tmp_path)
    (tmp_path / "inbox.txt").write_bytes("# my links\nhttps://example.com/a".encode("utf-8"))  # no trailing newline
    web.feeds[CID] = feed("القناة", [V(2), V(1)])
    _check(tmp_path)
    lines = (tmp_path / "inbox.txt").read_text(encoding="utf-8").splitlines()
    assert lines[:2] == ["# my links", "https://example.com/a"] and lines[2].startswith("https://www.youtube.com/watch?v=vid002xxxx")


def test_check_skips_links_already_in_inbox_or_already_processed(web, tmp_path):
    _follow(web, tmp_path)
    (tmp_path / "inbox.txt").write_text("https://youtu.be/vid002xxxx\n", encoding="utf-8")  # same video, other spelling
    st = ib.empty_state()
    st["processed"]["youtube:vid003xxxx"] = {"link": "x", "status": "ok"}
    ib.save_state(tmp_path / ib.STATE_NAME, st)
    web.feeds[CID] = feed("القناة", [V(4), V(3), V(2), V(1)])
    code, rep, _ = _check(tmp_path)
    assert [v.id for _t, v in rep.added] == ["vid004xxxx"] and rep.already_known == 2
    assert len(_inbox_links(tmp_path)) == 2


def test_check_max_per_channel_takes_newest_and_drops_older(web, tmp_path):
    _follow(web, tmp_path)
    web.feeds[CID] = feed("القناة", [V(i) for i in range(9, 0, -1)])
    code, rep, out = _check(tmp_path, max_per_channel=3)
    assert [v.id for _t, v in rep.added] == ["vid009xxxx", "vid008xxxx", "vid007xxxx"] and rep.skipped_old == 5 and "تخطيتُ 5" in out
    assert _check(tmp_path, max_per_channel=3)[1].added == []  # the dropped ones are not re-offered


def test_one_failing_channel_does_not_stop_the_others_and_all_failing_is_exit_4(web, tmp_path):
    _follow(web, tmp_path, title="A")
    _follow(web, tmp_path, title="B", cid=CID2)
    web.feeds[CID] = feed("A", [V(2), V(1)])
    web.fail[CID2] = 99
    web.feeds[CID2] = feed("B", [V(2), V(1)])
    code, rep, out = _check(tmp_path)
    assert code == 0 and rep.failed == 1 and len(rep.added) == 1 and "B:" in out and "مؤقتًا" in out
    assert ch.load(tmp_path)["channels"][CID2]["last_error"]
    web.fail[CID] = 99
    web.feeds[CID] = feed("A", [V(3), V(2), V(1)])
    assert _check(tmp_path)[0] == 4


def test_dry_run_writes_nothing(web, tmp_path):
    _follow(web, tmp_path)
    web.feeds[CID] = feed("القناة", [V(2), V(1)])
    before = (tmp_path / ch.STATE_NAME).read_text(encoding="utf-8")
    code, rep, out = _check(tmp_path, dry_run=True)
    assert code == 0 and len(rep.added) == 1 and "vid002xxxx" in out
    assert not (tmp_path / "inbox.txt").exists() and (tmp_path / ch.STATE_NAME).read_text(encoding="utf-8") == before
    assert len(_check(tmp_path)[1].added) == 1  # the real check still finds it


def test_check_with_no_channels_and_with_corrupt_state(web, tmp_path):
    assert _check(tmp_path)[0] == 0
    (tmp_path / ch.STATE_NAME).write_text("{oops", encoding="utf-8")
    code, _rep, out = _check(tmp_path)
    assert code == 2 and "تالف" in out
    assert cli.main(["channels", "list", "--data-dir", str(tmp_path)]) == 2


def test_seen_list_is_capped(web, tmp_path):
    _follow(web, tmp_path)
    c = ch.load(tmp_path)
    c["channels"][CID]["seen"] = [f"old{i:05d}xx" for i in range(ch.MAX_SEEN + 50)]
    ch.save(c, tmp_path)
    web.feeds[CID] = feed("القناة", [V(2), V(1)])
    _check(tmp_path)
    assert len(ch.load(tmp_path)["channels"][CID]["seen"]) == ch.MAX_SEEN


# ------------------------------------------------------------------ CLI and the morning hook
def test_cli_channels_flow(web, tmp_path, capsys):
    web.pages["https://www.youtube.com/@NASA"] = page(CID)
    web.feeds[CID] = feed("NASA", [V(1)])
    d = str(tmp_path)
    assert cli.main(["channels", "add", "@NASA", "--data-dir", d]) == 0
    assert cli.main(["channels", "list", "--data-dir", d]) == 0
    web.feeds[CID] = feed("NASA", [V(2), V(1)])
    assert cli.main(["channels", "check", "--dry-run", "--data-dir", d]) == 0
    assert not (tmp_path / "inbox.txt").exists()
    assert cli.main(["channels", "--data-dir", d, "check"]) == 0 and len(_inbox_links(tmp_path)) == 1
    assert cli.main(["channels", "check", "--max-per-channel", "0", "--data-dir", d]) == 2
    assert cli.main(["channels", "remove", "@NASA", "--data-dir", d]) == 0
    assert cli.main(["channels", "add", "https://www.youtube.com/watch?v=1", "--data-dir", d]) == 2
    assert "NASA" in capsys.readouterr().out


def _morning_setup(web, tmp_path):
    _follow(web, tmp_path, title="Chan")
    web.feeds[CID] = feed("Chan", [V(2, "جديد"), V(1)])
    (tmp_path / "inbox.txt").write_text("# mine\n", encoding="utf-8")


def test_morning_checks_channels_first_and_digests_the_new_video(web, tmp_path, capsys):
    _morning_setup(web, tmp_path)
    assert cli.main(["morning", "--sample", "--channels", "--data-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "فحص القنوات" in out and "ملخص صباحي" in out
    st = json.loads((tmp_path / ib.SAMPLE_STATE_NAME).read_text(encoding="utf-8"))
    assert list(st["processed"]) == ["youtube:vid002xxxx"]  # the channel's new video went through the digest


def test_morning_checks_channels_by_default_in_real_mode_even_if_login_is_missing(web, tmp_path):
    _morning_setup(web, tmp_path)
    assert cli.main(["morning", "--data-dir", str(tmp_path)]) == 3  # no NotebookLM login on this machine
    assert _inbox_links(tmp_path) == ["https://www.youtube.com/watch?v=vid002xxxx"]  # link waits in the inbox for tomorrow


def test_morning_sample_skips_channels_by_default_and_opt_outs_work(web, tmp_path, monkeypatch):
    _morning_setup(web, tmp_path)
    n_calls = len(web.calls)
    assert cli.main(["morning", "--sample", "--data-dir", str(tmp_path)]) == 0
    assert _inbox_links(tmp_path) == [] and len(web.calls) == n_calls  # no network, real inbox untouched
    assert cli.main(["morning", "--no-channels", "--data-dir", str(tmp_path)]) == 0  # inbox empty -> nothing to do, no login needed
    assert _inbox_links(tmp_path) == []
    monkeypatch.setenv("NOTEBOOKLM_LAB_CHANNELS_AUTO", "0")
    assert cli.main(["morning", "--data-dir", str(tmp_path)]) == 0
    assert _inbox_links(tmp_path) == []
    assert cli.main(["morning", "--channels", "--data-dir", str(tmp_path)]) == 3  # explicit flag beats the env setting
    assert len(_inbox_links(tmp_path)) == 1


def test_a_crashing_channel_check_never_breaks_morning(web, tmp_path, monkeypatch, capsys):
    _morning_setup(web, tmp_path)
    monkeypatch.setattr(ch, "check", lambda *a, **k: 1 / 0)
    (tmp_path / "inbox.txt").write_text("https://example.com/a\n", encoding="utf-8")
    assert cli.main(["morning", "--sample", "--channels", "--data-dir", str(tmp_path)]) == 0
    assert "تعذّر" in capsys.readouterr().out


def test_morning_without_followed_channels_makes_no_network_call_and_no_noise(web, tmp_path, capsys):
    (tmp_path / "inbox.txt").write_text("https://example.com/a\n", encoding="utf-8")
    assert cli.main(["morning", "--channels", "--sample", "--data-dir", str(tmp_path)]) == 0
    assert web.calls == [] and "فحص القنوات" not in capsys.readouterr().out
