import asyncio
import json
import os
import sys

import pytest

from notebooklm_lab import askboth, cli, mcp_server, real_backend, vault_search
from notebooklm_lab.sample_backend import SampleBackend
from tests.test_askall import FakeBackend, _call


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    (v / ".obsidian").mkdir(parents=True)
    (v / "Notes").mkdir()
    (v / "Archive").mkdir()
    (v / ".trash").mkdir()
    (v / "Notes" / "الهوك.md").write_text(
        "---\ntags: [محتوى, فيديو]\n---\n# كيف تكتب هوك قوي\nالهوك هو أول ثلاث ثوانٍ في الفيديو القصير. **البداية القوية** ترفع نسبة المشاهدة.\n", encoding="utf-8")
    (v / "Notes" / "ميزانية.md").write_text("# الميزانية الشهرية\nنصائح عن الادخار والمصروفات.\n", encoding="utf-8")
    (v / "Notes" / "hooks.md").write_text("# Short video hooks\nA strong hook in the first 3 seconds improves retention.\n", encoding="utf-8")
    (v / "Archive" / "old.md").write_text("# قديم\nالهوك القديم والفيديو.\n", encoding="utf-8")
    (v / ".trash" / "deleted.md").write_text("# محذوف\nالهوك الهوك الهوك القوي الفيديو\n", encoding="utf-8")
    (v / ".obsidian" / "x.md").write_text("الهوك القوي", encoding="utf-8")
    (v / "Notes" / "image.png").write_bytes(b"\x89PNG")
    return v


# ------------------------------------------------------------------ vault search
def test_ranking_title_and_coverage_beat_passing_mentions(vault):
    res = vault_search.search(vault, "ما هو الهوك القوي في الفيديوهات القصيرة؟")
    assert res.hits[0].path == "Notes/الهوك.md"
    assert res.hits[0].title == "كيف تكتب هوك قوي" and set(res.hits[0].matched) >= {"هوك", "قوي"}
    assert res.hits[0].tags == ["محتوى", "فيديو"]
    scores = [h.score for h in res.hits]
    assert scores == sorted(scores, reverse=True)


def test_hidden_and_non_markdown_files_are_skipped(vault):
    res = vault_search.search(vault, "الهوك القوي")
    paths = [h.path for h in res.hits]
    assert not any(p.startswith((".trash", ".obsidian")) for p in paths) and not any(p.endswith(".png") for p in paths)
    assert res.files_scanned == 4


def test_arabic_normalisation_diacritics_hamza_ta_marbuta_and_punctuation(vault):
    (vault / "Notes" / "تشكيل.md").write_text("# إدارة الوقت\nأَهَمِّيَّةُ التَّخْطِيطِ اليومي\n", encoding="utf-8")
    for q in ("اداره الوقت", "أهمية التخطيط", "الوقت؟", "التخطيط،"):
        res = vault_search.search(vault, q)
        assert res.hits and res.hits[0].path == "Notes/تشكيل.md", q
    assert "؟" not in "".join(vault_search.query_terms("ما هو الهوك؟"))


def test_english_and_inflected_forms(vault):
    assert vault_search.search(vault, "short video hook retention").hits[0].path == "Notes/hooks.md"
    assert vault_search.search(vault, "hooks").hits[0].path == "Notes/hooks.md"


def test_no_match_and_stop_words_only(vault):
    assert vault_search.search(vault, "كلمةغيرموجودة").hits == []
    res = vault_search.search(vault, "ما هو في")  # only stop words -> falls back, never crashes
    assert isinstance(res.hits, list)


def test_snippet_is_clean_and_around_the_match(vault):
    h = vault_search.search(vault, "المشاهدة").hits[0]
    assert "المشاهدة" in h.snippet and "**" not in h.snippet and "#" not in h.snippet and len(h.snippet) <= 400


def test_folder_filter_and_guards(vault, tmp_path):
    res = vault_search.search(vault, "الهوك", folder="Archive")
    assert [h.path for h in res.hits] == ["Archive/old.md"]
    with pytest.raises(ValueError):
        vault_search.search(vault, "الهوك", folder="../outside")
    with pytest.raises(ValueError):
        vault_search.search(vault, "الهوك", folder="Nope")


def test_symlink_pointing_outside_vault_is_not_read(vault, tmp_path):
    outside = tmp_path / "secret.md"
    outside.write_text("# سر\nالهوك القوي كلمة سرية", encoding="utf-8")
    try:
        (vault / "Notes" / "link.md").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks not available")
    assert all("سر" not in h.title for h in vault_search.search(vault, "الهوك القوي").hits)


def test_large_vault_is_capped_and_big_files_not_fully_read(vault, monkeypatch):
    monkeypatch.setattr(vault_search, "MAX_FILES", 5)
    for i in range(20):
        (vault / "Notes" / f"n{i}.md").write_text(f"# n{i}\nالهوك {i}", encoding="utf-8")
    res = vault_search.search(vault, "الهوك")
    assert res.truncated and res.files_scanned <= 5
    monkeypatch.undo()
    big = vault / "Notes" / "big.md"
    big.write_text("# كبير\n" + ("حشو " * 600_000) + " كلمةنادرة", encoding="utf-8")
    assert vault_search.search(vault, "كلمةنادرة").hits == []  # beyond the read cap: ignored, but no crash / no huge read


def test_limit_is_respected(vault):
    assert len(vault_search.search(vault, "الهوك الفيديو", limit=1).hits) == 1


# ------------------------------------------------------------------ combined run
def _combined(vault, tmp_path, backend=None, **kw):
    kw.setdefault("data_dir", tmp_path / "d")
    return asyncio.run(askboth.run_combined("ما هو الهوك القوي؟", backend_factory=(lambda: backend) if backend else None, vault=str(vault), **kw))


def test_combined_cites_both_notes_by_path_and_notebooks_by_name(vault, tmp_path):
    c = _combined(vault, tmp_path, FakeBackend(), flt=None)
    md = askboth.render_markdown(c)
    assert "[ملاحظة 1]" in md and "`Notes/الهوك.md`" in md and str(vault.resolve()) in md
    assert "من دفتر «ملخص صباحي 2026-11-04»" in md and "[1.1]" in md
    assert askboth.exit_code(c) == 0
    html = askboth.render_html(c)
    assert "<html" in html and "Notes/الهوك.md" in html and "ملخص صباحي" in html


def test_vault_only_does_not_touch_notebooks(vault, tmp_path):
    fb = FakeBackend()
    c = _combined(vault, tmp_path, fb, include_notebooks=False)
    assert fb.asked == [] and c.notebooks is None and c.has_notes and askboth.exit_code(c) == 0


def test_notebooks_login_missing_still_returns_the_notes(vault, tmp_path):
    c = _combined(vault, tmp_path, real_backend.RealBackend())
    assert c.notebooks_login and c.has_notes
    md = askboth.render_markdown(c)
    assert "NotebookLM لم يُفحص" in md and "[ملاحظة 1]" in md
    assert askboth.exit_code(c) == 0


def test_vault_missing_still_returns_notebooks(vault, tmp_path):
    c = _combined(tmp_path / "nope", tmp_path, FakeBackend())
    assert c.vault_error and "غير موجود" in c.vault_error and c.has_notebook_answers
    assert "Obsidian لم يُفحص" in askboth.render_markdown(c) and askboth.exit_code(c) == 0


def test_nothing_searchable_exit_codes(vault, tmp_path):
    only_login = _combined(tmp_path / "nope", tmp_path, real_backend.RealBackend())
    assert askboth.exit_code(only_login) == askboth.EXIT_LOGIN
    no_vault_no_nb = _combined(tmp_path / "nope", tmp_path, None)
    assert askboth.exit_code(no_vault_no_nb) == askboth.EXIT_USAGE
    all_failed = _combined(tmp_path / "nope", tmp_path, FakeBackend(answers={f"nb{i}": RuntimeError("boom") for i in range(1, 6)}))
    assert askboth.exit_code(all_failed) == askboth.EXIT_FAILED


def test_no_match_anywhere_is_ok_and_says_so(vault, tmp_path):
    c = asyncio.run(askboth.run_combined("كلمةغيرموجودة", backend_factory=None, vault=str(vault), data_dir=tmp_path / "d", include_notebooks=False))
    assert askboth.exit_code(c) == 0 and "لا توجد ملاحظات تطابق" in askboth.render_markdown(c)


def test_save_report_writes_md_html_json_without_overwriting(vault, tmp_path):
    c = _combined(vault, tmp_path, FakeBackend())
    root = tmp_path / "out"
    d1 = askboth.save_report(c, root)
    d2 = askboth.save_report(c, root)
    assert d1 != d2 and {p.name for p in d1.iterdir()} == {"report.md", "report.html", "answer.json"}
    data = json.loads((d1 / "answer.json").read_text(encoding="utf-8"))
    assert data["vault_result"]["hits"][0]["path"] == "Notes/الهوك.md"


def test_notes_with_html_are_escaped_in_the_report(vault, tmp_path):
    (vault / "Notes" / "xss.md").write_text("# <script>alert(1)</script> الهوك\nالهوك القوي <img src=x onerror=1>", encoding="utf-8")
    html = askboth.render_html(_combined(vault, tmp_path, None, include_notebooks=False))
    assert "<script>alert" not in html and "<img src=x" not in html


# ------------------------------------------------------------------ CLI
def test_cli_ask_both_sample_with_real_vault(vault, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(vault))
    rc = cli.main(["ask-both", "ما", "هو", "الهوك", "القوي؟", "--sample", "--data-dir", str(tmp_path / "d")])
    out = capsys.readouterr().out
    assert rc == 0 and "[ملاحظة 1]" in out and "[عينة]" in out and "report.html" in out
    assert list((tmp_path / "d" / "ask-both-sample").iterdir())


def test_cli_ask_both_json_is_pure_json_on_stdout(vault, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(vault))
    rc = cli.main(["ask-both", "الهوك", "--sample", "--json", "--data-dir", str(tmp_path / "d")])
    cap = capsys.readouterr()
    assert rc == 0 and json.loads(cap.out)["vault_result"]["hits"]


def test_cli_ask_both_no_notebooks_needs_no_login(vault, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(vault))
    rc = cli.main(["ask-both", "الهوك", "--no-notebooks", "--data-dir", str(tmp_path / "d")])
    assert rc == 0 and "(لم يُفحص)" in capsys.readouterr().out


def test_cli_ask_both_exit_codes(vault, tmp_path, monkeypatch, capsys):
    d = str(tmp_path / "d")
    monkeypatch.delenv("OBSIDIAN_VAULT", raising=False)
    assert cli.main(["ask-both", "x", "--no-notebooks", "--data-dir", d]) == 2  # vault not configured
    assert cli.main(["ask-both", "x", "--no-vault", "--no-notebooks", "--data-dir", d]) == 2
    assert cli.main(["ask-both", "x", "--no-vault", "--data-dir", d]) == 3  # real backend, no login
    assert "login" in capsys.readouterr().out


def test_cli_obsidian_search(vault, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(vault))
    assert cli.main(["obsidian", "search", "الهوك", "القوي", "--data-dir", str(tmp_path / "d")]) == 0
    assert "Notes/الهوك.md" in capsys.readouterr().out
    assert cli.main(["obsidian", "search", "الهوك", "--folder", "../x", "--data-dir", str(tmp_path / "d")]) == 2


# ------------------------------------------------------------------ MCP
def test_mcp_ask_vault_and_notebooks_in_process(vault, tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(vault))
    server = mcp_server.build_server(lambda: SampleBackend(), tmp_path / "d", sample=True)
    res = _call(server, "ask_vault_and_notebooks", {"question": "ما الهوك القوي؟", "match": ["ملاحظات"]})
    text = res.content[0].text
    assert not res.is_error and "[ملاحظة 1]" in text and "Notes/الهوك.md" in text and "من دفتر «[عينة] ملاحظات صانع المحتوى»" in text
    assert list((tmp_path / "d" / "ask-both-sample").iterdir())


def test_mcp_search_obsidian_vault_and_errors(vault, tmp_path, monkeypatch):
    server = mcp_server.build_server(lambda: SampleBackend(), tmp_path / "d", sample=True)
    monkeypatch.delenv("OBSIDIAN_VAULT", raising=False)
    assert _call(server, "search_obsidian_vault", {"query": "الهوك"}).is_error
    monkeypatch.setenv("OBSIDIAN_VAULT", str(vault))
    ok = _call(server, "search_obsidian_vault", {"query": "الهوك القوي"})
    assert not ok.is_error and "Notes/الهوك.md" in ok.content[0].text and "untrusted" in ok.content[0].text
    assert _call(server, "search_obsidian_vault", {"query": "  "}).is_error
    assert _call(server, "search_obsidian_vault", {"query": "x", "folder": "../.."}).is_error
    assert _call(server, "ask_vault_and_notebooks", {"question": "x", "include_vault": False, "include_notebooks": False}).is_error


def test_mcp_without_login_degrades_to_notes(vault, tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(vault))
    server = mcp_server.build_server(lambda: real_backend.RealBackend(), tmp_path / "d")
    res = _call(server, "ask_vault_and_notebooks", {"question": "الهوك القوي"})
    assert not res.is_error and "[ملاحظة 1]" in res.content[0].text and "NotebookLM لم يُفحص" in res.content[0].text


def test_mcp_stdio_search_tool_with_real_vault(vault, tmp_path):
    pytest.importorskip("mcp")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def go():
        env = {**os.environ, "NOTEBOOKLM_LAB_DATA": str(tmp_path / "d"), "NOTEBOOKLM_HOME": str(tmp_path / "h"), "OBSIDIAN_VAULT": str(vault)}
        params = StdioServerParameters(command=sys.executable, args=["-m", "notebooklm_lab", "mcp-server", "--sample"], env=env)
        async with stdio_client(params, errlog=open(os.devnull, "w")) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                a = await s.call_tool("search_obsidian_vault", {"query": "الهوك القوي"})
                b = await s.call_tool("ask_vault_and_notebooks", {"question": "الهوك القوي", "match": ["ملاحظات"]})
                return a.content[0].text, b.content[0].text

    a, b = asyncio.run(asyncio.wait_for(go(), 60))
    assert "Notes/الهوك.md" in a and "[ملاحظة 1]" in b and "[عينة]" in b
