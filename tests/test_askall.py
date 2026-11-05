import asyncio
import json
from types import SimpleNamespace as NS

import notebooklm
import pytest

from notebooklm_lab import askall, cli, mcp_server, real_backend, storage
from notebooklm_lab.models import QA, Citation, NotebookInfo
from notebooklm_lab.sample_backend import SampleBackend


def NB(i, title, n=3):
    return NotebookInfo(f"nb{i}", title, n)


NOTEBOOKS = [NB(1, "ملخص صباحي 2026-11-04"), NB(2, "Python Notes"), NB(3, "Empty one", 0), NB(4, "ملخص صباحي 2026-11-03"), NB(5, "Finance")]


class FakeBackend(SampleBackend):
    mode = "real"

    def __init__(self, answers=None, notebooks=None, delay=0.0):
        super().__init__()
        self.answers, self.nbs, self.delay = answers or {}, notebooks if notebooks is not None else NOTEBOOKS, delay
        self.asked, self.running, self.peak = [], 0, 0

    async def list_notebooks(self):
        return list(self.nbs)

    async def ask(self, notebook_id, question, language):
        self.asked.append((notebook_id, question))
        self.running += 1
        self.peak = max(self.peak, self.running)
        try:
            await asyncio.sleep(self.delay)
            a = self.answers.get(notebook_id, f"جواب {notebook_id} [1] و[2]")
            if isinstance(a, Exception):
                raise a
            return QA(question, a, [Citation(1, "s1", f"مصدر {notebook_id}", "نص المقتطف " * 40), Citation(2, "s2", "مصدر ثان", "x")])
        finally:
            self.running -= 1


def _run(backend, question="سؤال؟", flt=None, **kw):
    async def go():
        async with backend:
            return await askall.ask_all(backend, question, flt, **kw)

    return asyncio.run(go())


# ------------------------------------------------------------------ selection
def test_select_default_skips_empty_and_applies_limit():
    chosen, skipped = askall.select_notebooks(NOTEBOOKS, askall.Filters(limit=3))
    assert [n.id for n in chosen] == ["nb1", "nb2", "nb4"]
    assert dict((n.id, why) for n, why in skipped)["nb3"] == "لا يحتوي مصادر" and "limit" in dict((n.id, why) for n, why in skipped)["nb5"]


def test_select_match_exclude_ids_morning_include_empty():
    sel = lambda **k: [n.id for n in askall.select_notebooks(NOTEBOOKS, askall.Filters(**k))[0]]
    assert sel(match=["python"]) == ["nb2"]  # case-insensitive
    assert sel(match=["python", "FINANCE"]) == ["nb2", "nb5"]
    assert sel(match=["ملخص"], exclude=["03"]) == ["nb1"]
    assert sel(ids=["nb5", "nb2"]) == ["nb2", "nb5"]
    assert sel(morning_only=True) == ["nb1", "nb4"]
    assert "nb3" in sel(include_empty=True)
    assert sel(match=["zzz"]) == []


def test_looks_unanswered_only_for_short_negative_answers():
    assert askall.looks_unanswered("لا تحتوي المصادر على معلومات عن هذا.")
    assert askall.looks_unanswered("The sources do not contain information about this.")
    assert not askall.looks_unanswered("الجواب: " + "تفاصيل " * 100 + " لا تحتوي")
    assert not askall.looks_unanswered("القصص القصيرة تنجح بسبب الهوك.")


def test_renumber_citations_per_notebook():
    assert askall.renumber("أ [1] ب [12] ج [x] [1,2]", 3) == "أ [3.1] ب [3.12] ج [x] [1,2]"


# ------------------------------------------------------------------ asking
def test_ask_all_asks_arabic_suffix_collects_and_survives_failures():
    b = FakeBackend({"nb2": RuntimeError("boom"), "nb4": "لا تحتوي المصادر على جواب."})
    res = _run(b, "ما هو الهوك؟", askall.Filters(limit=5))
    assert [a.notebook.id for a in res.answers] == ["nb1", "nb2", "nb4", "nb5"]
    assert all(q.startswith("ما هو الهوك؟") and "أجب بالعربية" in q for _i, q in b.asked)
    by = {a.notebook.id: a for a in res.answers}
    assert by["nb1"].ok and not by["nb1"].no_answer and by["nb2"].error and "boom" in by["nb2"].error and by["nb4"].no_answer
    assert [a.notebook.id for a in res.useful] == ["nb1", "nb5"] and askall.exit_code(res) == 0
    assert res.skipped == [("Empty one", "لا يحتوي مصادر")] and res.total_notebooks == 5


def test_ask_all_timeout_is_per_notebook_and_concurrency_is_limited():
    res = _run(FakeBackend(delay=0.4), flt=askall.Filters(limit=5), timeout_s=0.05)
    assert all("المهلة" in a.error for a in res.answers) and askall.exit_code(res) == askall.EXIT_FAILED
    b = FakeBackend(delay=0.05)
    _run(b, flt=askall.Filters(limit=5), concurrency=2)
    assert b.peak == 2 and len(b.asked) == 4


def test_no_match_exit_code():
    res = _run(FakeBackend(), flt=askall.Filters(match=["zzz"]))
    assert res.answers == [] and askall.exit_code(res) == askall.EXIT_USAGE


# ------------------------------------------------------------------ rendering + saving
def test_markdown_names_notebooks_renumbers_and_lists_skipped():
    res = _run(FakeBackend({"nb2": RuntimeError("x"), "nb4": "لا تحتوي المصادر على جواب."}), "س", askall.Filters(limit=4))
    md = askall.render_markdown(res)
    assert "من دفتر «ملخص صباحي 2026-11-04»" in md and "[1.1]" in md and "[1.2]" in md and "جواب nb1 [1.1]" in md
    assert "### 4. من دفتر «Finance»" in md and "جواب nb5 [4.1] و[4.2]" in md  # numbering follows the notebook's position
    assert "## دفاتر لم تُفد" in md and "«Python Notes» — فشل" in md and "«Empty one» — لم يُسأل" in md
    assert "أجاب 2 بمعلومات" in md and "…" in md  # long citation text is cut


def test_html_escapes_everything_and_is_rtl():
    evil = "<script>alert(1)</script>"
    b = FakeBackend({"nb1": f"x {evil} [1]"}, notebooks=[NB(1, f"دفتر {evil}")])
    html = askall.render_html(_run(b, f"س {evil}"))
    assert "<script>alert" not in html and "&lt;script&gt;" in html and "dir='rtl'" in html and "[1.1]" in html


def test_save_report_writes_three_files_in_new_folders(tmp_path):
    res = _run(FakeBackend())
    d1 = askall.save_report(res, tmp_path)
    d2 = askall.save_report(res, tmp_path)
    assert d1 != d2 and {p.name for p in d1.iterdir()} == {"report.md", "report.html", "answer.json"}
    data = json.loads((d1 / "answer.json").read_text(encoding="utf-8"))
    assert data["question"] == "سؤال؟" and data["answers"][0]["notebook"]["id"] == "nb1"
    assert not any(c in d1.name for c in '?<>:"|*')


# ------------------------------------------------------------------ real backend (fake client)
class _FakeClient:
    def __init__(self):
        self.notebooks = NS(list=self._list)
        self.sources = NS(list=self._slist)
        self.chat = NS(ask=self._ask)
        self.source_list_calls = 0

    async def _list(self):
        return [NS(id="a", title="دفتر أ", sources_count=2), NS(id="b", title="دفتر ب", sources_count=0)]

    async def _slist(self, nb):
        self.source_list_calls += 1
        return [NS(id="s1", title="عنوان المصدر الأول")]

    async def _ask(self, nb, q):
        return NS(answer="جواب [1]", references=[NS(source_id="s1", citation_number=1, cited_text="مقتطف")])


class _Ctx:
    def __init__(self, c): self.c = c
    async def __aenter__(self): return self.c
    async def __aexit__(self, *a): return None


def test_real_backend_lists_notebooks_and_names_cited_sources(monkeypatch):
    client = _FakeClient()
    monkeypatch.setattr(storage, "has_session", lambda *a, **k: True)
    monkeypatch.setattr(notebooklm.NotebookLMClient, "from_storage", staticmethod(lambda **kw: _Ctx(client)))

    async def go():
        async with real_backend.RealBackend() as b:
            nbs = await b.list_notebooks()
            qa1 = await b.ask("a", "q", "ar_001")
            await b.ask("a", "q", "ar_001")
            return nbs, qa1

    nbs, qa = asyncio.run(go())
    assert [(n.id, n.title, n.sources_count) for n in nbs] == [("a", "دفتر أ", 2), ("b", "دفتر ب", 0)]
    assert qa.citations[0].source_title == "عنوان المصدر الأول" and client.source_list_calls == 1  # cached


def test_real_backend_ask_still_works_when_source_titles_cannot_be_loaded(monkeypatch):
    client = _FakeClient()

    async def boom(nb):
        raise RuntimeError("nope")

    client.sources = NS(list=boom)
    monkeypatch.setattr(storage, "has_session", lambda *a, **k: True)
    monkeypatch.setattr(notebooklm.NotebookLMClient, "from_storage", staticmethod(lambda **kw: _Ctx(client)))

    async def go():
        async with real_backend.RealBackend() as b:
            return await b.ask("a", "q", "ar_001")

    assert asyncio.run(go()).citations[0].source_title == "s1"


# ------------------------------------------------------------------ CLI
def test_cli_sample_prints_combined_answer_and_saves_report(tmp_path, capsys):
    assert cli.main(["ask-all", "ما", "أهم", "الأفكار؟", "--sample", "--data-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "إجابة مجمّعة" in out and "من دفتر «[عينة] ملخص صباحي 2026-11-01»" in out and "[3.1]" in out
    runs = list((tmp_path / "ask-sample").iterdir())
    assert len(runs) == 1 and (runs[0] / "report.html").is_file()


def test_cli_filters_json_and_usage_errors(tmp_path, capsys):
    assert cli.main(["ask-all", "س", "--sample", "--match", "ملاحظات", "--json", "--data-dir", str(tmp_path)]) == 0
    cap = capsys.readouterr()
    data = json.loads(cap.out)  # stdout is pure JSON; progress went to stderr
    assert [a["notebook"]["title"] for a in data["answers"]] == ["[عينة] ملاحظات صانع المحتوى"] and "عدد الدفاتر" in cap.err
    assert cli.main(["ask-all", "س", "--sample", "--match", "zzz", "--data-dir", str(tmp_path)]) == 2
    assert cli.main(["ask-all", "س", "--sample", "--limit", "0", "--data-dir", str(tmp_path)]) == 2
    assert cli.main(["ask-all", "س", "--sample", "--morning", "--limit", "1", "--data-dir", str(tmp_path)]) == 0
    assert "أجاب 1" in capsys.readouterr().out


def test_cli_without_login_is_friendly_exit_3_and_creates_nothing(tmp_path, capsys):
    assert cli.main(["ask-all", "س", "--data-dir", str(tmp_path)]) == 3
    assert "login" in capsys.readouterr().out and not (tmp_path / "ask").exists()


def test_cli_all_notebooks_failing_is_exit_4(tmp_path, monkeypatch):
    monkeypatch.setattr(SampleBackend, "ask", lambda self, *a: (_ for _ in ()).throw(RuntimeError("down")))
    assert cli.main(["ask-all", "س", "--sample", "--data-dir", str(tmp_path)]) == 4


def test_cli_auth_error_while_listing_is_exit_3(tmp_path, monkeypatch):
    async def bad(self):
        raise RuntimeError("Authentication expired")

    monkeypatch.setattr(SampleBackend, "list_notebooks", bad)
    assert cli.main(["ask-all", "س", "--sample", "--data-dir", str(tmp_path)]) == 3


# ------------------------------------------------------------------ MCP tool
fastmcp = pytest.importorskip("fastmcp")


def _call(server, tool, args):
    async def go():
        async with fastmcp.Client(server) as c:
            return await c.call_tool(tool, args, raise_on_error=False)

    return asyncio.run(go())


def test_mcp_server_lists_the_tool_with_arabic_friendly_description(tmp_path):
    server = mcp_server.build_server(lambda: SampleBackend(), tmp_path, sample=True)

    async def go():
        async with fastmcp.Client(server) as c:
            return await c.list_tools()

    tools = {t.name: t for t in asyncio.run(go())}
    assert {"ask_all_notebooks", "ask_vault_and_notebooks", "search_obsidian_vault"} == set(tools)
    t = tools["ask_all_notebooks"]
    schema = getattr(t, "input_schema", None) or t.inputSchema
    assert "question" in schema["properties"] and "ALL" in t.description


def test_mcp_tool_returns_combined_answer_and_report_path(tmp_path):
    server = mcp_server.build_server(lambda: SampleBackend(), tmp_path, sample=True)
    res = _call(server, "ask_all_notebooks", {"question": "ما الهوك؟", "match": ["ملاحظات"]})
    text = res.content[0].text
    assert not res.is_error and "من دفتر «[عينة] ملاحظات صانع المحتوى»" in text and "saved report" in text
    assert list((tmp_path / "ask-sample").iterdir())
    none = _call(server, "ask_all_notebooks", {"question": "x", "match": ["zzz"]})
    assert "No notebook matched" in none.content[0].text


def test_mcp_tool_errors_are_clear(tmp_path):
    server = mcp_server.build_server(lambda: real_backend.RealBackend(), tmp_path)
    res = _call(server, "ask_all_notebooks", {"question": "x"})
    assert res.is_error and "login" in res.content[0].text.lower()
    res2 = _call(mcp_server.build_server(lambda: SampleBackend(), tmp_path, sample=True), "ask_all_notebooks", {"question": "  "})
    assert res2.is_error


def test_mcp_server_over_stdio_with_sample_data(tmp_path):
    pytest.importorskip("mcp")
    import os
    import sys

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def go():
        env = {**os.environ, "NOTEBOOKLM_LAB_DATA": str(tmp_path / "d"), "NOTEBOOKLM_HOME": str(tmp_path / "h")}
        params = StdioServerParameters(command=sys.executable, args=["-m", "notebooklm_lab", "mcp-server", "--sample"], env=env)
        async with stdio_client(params, errlog=open(os.devnull, "w")) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                names = [t.name for t in (await s.list_tools()).tools]
                out = await s.call_tool("ask_all_notebooks", {"question": "ما أهم فكرة؟"})
                return names, out.content[0].text

    names, text = asyncio.run(asyncio.wait_for(go(), 60))
    assert sorted(names) == ["ask_all_notebooks", "ask_vault_and_notebooks", "search_obsidian_vault"] and "إجابة مجمّعة" in text
