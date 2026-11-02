import pytest

from notebooklm_lab.sources import SourceError, build_specs, classify, read_links_file


def test_classify_url_youtube_file(tmp_path):
    assert classify("https://example.com/a").kind == "url"
    assert classify("https://www.youtube.com/watch?v=abc").kind == "youtube"
    assert classify("https://youtu.be/abc").kind == "youtube"
    f = tmp_path / "n.md"
    f.write_text("x", encoding="utf-8")
    assert classify(str(f)).kind == "file"


@pytest.mark.parametrize("bad", ["", "ftp://x.org/a", "file:///etc/passwd", "javascript:alert(1)", "no-such-file.pdf"])
def test_classify_rejects(bad):
    with pytest.raises(SourceError):
        classify(bad)


def test_links_file_ignores_comments(tmp_path):
    f = tmp_path / "links.txt"
    f.write_text("# c\n\nhttps://a.org\n  https://b.org  \n", encoding="utf-8")
    assert read_links_file(f) == ["https://a.org", "https://b.org"]
    assert [s.value for s in build_specs(read_links_file(f))] == ["https://a.org", "https://b.org"]
