import asyncio
import json

from notebooklm_lab.models import SourceSpec
from notebooklm_lab.pipeline import make_run_dir, run_digest
from notebooklm_lab.sample_backend import DEMO_SPECS, SampleBackend


def run(tmp_path, specs=DEMO_SPECS, title="t", outputs=("briefing", "study_guide", "mind_map", "audio", "quiz")):
    d = make_run_dir(tmp_path, title)
    return d, asyncio.run(run_digest(SampleBackend(), specs, d, title, outputs=outputs))


def test_sample_end_to_end(tmp_path):
    d, res = run(tmp_path)
    assert res.mode == "sample"
    assert len(res.sources) == 3 and all(s.status == "ready" for s in res.sources)
    assert len(res.qa) == 3 and all(q.citations for q in res.qa)
    assert all(o.ok for o in res.outputs)
    for o in res.outputs:
        assert (d / o.path).is_file() and o.size_bytes > 0
    data = json.loads((d / "run.json").read_text(encoding="utf-8"))
    assert data["mode"] == "sample"
    assert "/" not in data["run_dir"]  # folder name only, no absolute path


def test_report_is_rtl_arabic_and_labelled_sample(tmp_path):
    d, _ = run(tmp_path)
    html = (d / "report.html").read_text(encoding="utf-8")
    assert "lang='ar' dir='rtl'" in html
    assert "بيانات تجريبية" in html and "SAMPLE DATA" in html
    assert "notebooklm-py" in html and "Google" in html
    assert "<audio controls src='files/audio_overview_SAMPLE_tone.wav'>" in html
    assert str(tmp_path) not in html  # relative links only


def test_report_escapes_html(tmp_path):
    spec = [SourceSpec("url", "https://e.com/?q=<script>alert(1)</script>", "<img src=x onerror=alert(1)>")]
    d, _ = run(tmp_path, spec, title="<b>x</b>")
    html = (d / "report.html").read_text(encoding="utf-8")
    assert "<script>alert" not in html and "<img src=x" not in html and "<b>x</b>" not in html


def test_one_failed_output_does_not_stop_the_rest(tmp_path):
    d, res = run(tmp_path, outputs=("slide_deck", "briefing"))
    assert [o.ok for o in res.outputs] == [False, True]
    assert (d / "report.html").is_file()


class FailingSource(SampleBackend):
    async def add_source(self, nb, spec):
        raise RuntimeError("boom")


def test_all_sources_failing_skips_outputs_but_still_reports(tmp_path):
    d = make_run_dir(tmp_path, "x")
    res = asyncio.run(run_digest(FailingSource(), DEMO_SPECS, d, "x"))
    assert res.outputs == [] and res.qa == []
    assert any("no usable source" in w for w in res.warnings)
    assert (d / "report.html").is_file()


def test_unknown_output_rejected(tmp_path):
    import pytest

    d = make_run_dir(tmp_path, "x")
    with pytest.raises(ValueError):
        asyncio.run(run_digest(SampleBackend(), DEMO_SPECS, d, "x", outputs=("nope",)))
