"""Exercise RealBackend against a fake notebooklm client. This proves OUR code
calls the library with the right arguments; it does NOT prove Google accepts them."""
import asyncio
from pathlib import Path
from types import SimpleNamespace as NS

import notebooklm

from notebooklm_lab import real_backend, storage
from notebooklm_lab.models import SourceSpec
from notebooklm_lab.pipeline import make_run_dir, run_digest


class FakeArtifacts:
    def __init__(self, calls):
        self.calls = calls

    async def _gen(self, name, **kw):
        self.calls.append((name, kw))
        return NS(task_id="t1", is_failed=False, error=None)

    async def generate_report(self, nb, **kw): return await self._gen("generate_report", **kw)
    async def generate_audio(self, nb, **kw): return await self._gen("generate_audio", **kw)
    async def generate_quiz(self, nb, **kw): return await self._gen("generate_quiz", **kw)

    async def generate_mind_map(self, nb, **kw):
        self.calls.append(("generate_mind_map", kw))
        return NS(mind_map={"name": "root", "children": []}, note_id="n1")

    async def wait_for_completion(self, nb, task_id, timeout=0):
        self.calls.append(("wait", {"timeout": timeout}))
        return NS(is_failed=False, error=None)

    async def _dl(self, name, out, **kw):
        self.calls.append((name, kw))
        Path(out).write_bytes(b"data")
        return out

    async def download_report(self, nb, out, *a): return await self._dl("download_report", out)
    async def download_audio(self, nb, out, *a): return await self._dl("download_audio", out)
    async def download_quiz(self, nb, out, *a, **kw): return await self._dl("download_quiz", out, **kw)
    async def download_mind_map(self, nb, out, *a): return await self._dl("download_mind_map", out)


class FakeClient:
    def __init__(self):
        self.calls = []
        self.artifacts = FakeArtifacts(self.calls)
        self.notebooks = NS(create=self._create)
        self.sources = NS(add_url=self._add_url, add_file=self._add_file)
        self.chat = NS(ask=self._ask)

    async def _create(self, title):
        self.calls.append(("create", title))
        return NS(id="nb1")

    async def _add_url(self, nb, url, **kw):
        self.calls.append(("add_url", {"url": url, **kw}))
        if "bad" in url:
            raise RuntimeError("unreachable")
        return NS(id="s-" + url[-3:], title="T " + url)

    async def _add_file(self, nb, path, **kw):
        self.calls.append(("add_file", {"path": str(path), **kw}))
        return NS(id="s-file", title="file")

    async def _ask(self, nb, q):
        self.calls.append(("ask", q))
        return NS(answer="جواب [1]", references=[NS(source_id="s-com", citation_number=1, cited_text="مقتطف")])


class FakeCtx:
    def __init__(self, client): self.client = client
    async def __aenter__(self): return self.client
    async def __aexit__(self, *a): return None


def test_real_backend_flow_with_fake_client(tmp_path, monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(storage, "has_session", lambda *a, **k: True)
    monkeypatch.setattr(notebooklm.NotebookLMClient, "from_storage", staticmethod(lambda **kw: FakeCtx(client)))
    f = tmp_path / "n.md"
    f.write_text("x", encoding="utf-8")
    specs = [SourceSpec("url", "https://example.com"), SourceSpec("url", "https://bad.example"), SourceSpec("file", str(f))]
    run_dir = make_run_dir(tmp_path / "o", "t")

    async def go():
        async with real_backend.RealBackend() as b:
            return await run_digest(b, specs, run_dir, "t", "ar_001", ("briefing", "mind_map", "audio", "quiz"), ["س؟"])

    res = asyncio.run(go())
    assert res.mode == "real" and "notebooklm-py" in res.library_version
    assert [s.status for s in res.sources] == ["ready", "failed", "ready"]
    assert res.qa[0].citations[0].source_title.startswith("T https://example.com")
    assert all(o.ok for o in res.outputs), res.warnings
    names = [c[0] for c in client.calls]
    assert ("add_url", {"url": "https://example.com", "wait": True}) in client.calls
    gen_audio = next(c for c in client.calls if c[0] == "generate_audio")
    assert gen_audio[1]["language"] == "ar_001" and "العربية" in gen_audio[1]["instructions"]
    assert next(c for c in client.calls if c[0] == "generate_report")[1]["language"] == "ar_001"
    assert next(c for c in client.calls if c[0] == "download_quiz")[1] == {"output_format": "markdown"}
    assert {"wait", "download_report", "download_audio", "download_mind_map"} <= set(names)
    assert (run_dir / "files" / "audio_overview.m4a").is_file()
    assert (run_dir / "report.html").is_file()


def test_real_backend_requires_login(isolated_home):
    import pytest

    async def go():
        async with real_backend.RealBackend():
            pass

    with pytest.raises(real_backend.LoginRequiredError):
        asyncio.run(go())
