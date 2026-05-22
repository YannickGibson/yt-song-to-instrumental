import sys
from unittest.mock import MagicMock, patch

import pytest

from yt_song_to_instrumental.cli import _print_pipeline_report, main
from yt_song_to_instrumental.config import LabelConfig, Source
from yt_song_to_instrumental.pipeline import PipelineReport, TrackReport
from yt_song_to_instrumental.preview import PreviewReport


def _make_label_config(sources: list[Source] | None = None) -> LabelConfig:
    return LabelConfig({
        "channel": {"name": "Test", "description": "T"},
        "label": {"name": "TestLabel"},
        "templates": {
            "video_title": "<artist-name>",
            "video_description": "D",
            "album_playlist_name": "<artist-name> — <album-name>",
            "artist_playlist_name": "<artist-name>",
        },
        "create_playlists_for_collaborators": True,
        "sources": [{"url": s.url, "after_date": s.after_date} for s in (sources or [])],
    })


class TestListModels:
    def test_list_models_prints_output(self, capsys):
        with patch.object(sys, "argv", ["yt-instrumental", "--list-models"]):
            main()

        output = capsys.readouterr().out
        assert "htdemucs" in output
        assert "mdxnet" in output
        assert "GPU required" in output
        assert "Min memory" in output


class TestArgParsing:
    def test_url_required_when_no_sources(self):
        cfg = _make_label_config(sources=[])
        with patch("yt_song_to_instrumental.cli.load_label_config", return_value=cfg), \
             patch.object(sys, "argv", ["yt-instrumental"]):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 2

    def test_model_choices_enforced(self):
        with patch.object(sys, "argv", ["yt-instrumental", "https://yt.com/v", "--model", "fake_model"]):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 2

    def test_after_date_with_sources_errors(self):
        cfg = _make_label_config(sources=[Source(url="https://yt.com/c", after_date="20260101")])
        with patch("yt_song_to_instrumental.cli.load_label_config", return_value=cfg), \
             patch.object(sys, "argv", ["yt-instrumental", "--dry-run", "--after-date", "20260201"]):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 2


class TestSourcesDispatch:
    def test_dry_run_uses_preview_for_each_source(self):
        cfg = _make_label_config(sources=[
            Source(url="https://yt.com/a", after_date="20260101"),
            Source(url="https://yt.com/b", after_date=None),
        ])
        with patch("yt_song_to_instrumental.cli.load_label_config", return_value=cfg), \
             patch("yt_song_to_instrumental.cli.preview_url") as mock_preview, \
             patch("yt_song_to_instrumental.cli.HistoryDB"), \
             patch.object(sys, "argv", ["yt-instrumental", "--dry-run"]):
            mock_preview.return_value = PreviewReport(source_url="x", after_date=None)
            main()
        assert mock_preview.call_count == 2
        called_urls = [c.kwargs["url"] for c in mock_preview.call_args_list]
        assert called_urls == ["https://yt.com/a", "https://yt.com/b"]
        called_dates = [c.kwargs["after_date"] for c in mock_preview.call_args_list]
        assert called_dates == ["20260101", None]

    def test_explicit_url_overrides_sources(self):
        cfg = _make_label_config(sources=[Source(url="https://from-config", after_date=None)])
        with patch("yt_song_to_instrumental.cli.load_label_config", return_value=cfg), \
             patch("yt_song_to_instrumental.cli.preview_url") as mock_preview, \
             patch("yt_song_to_instrumental.cli.HistoryDB"), \
             patch.object(sys, "argv", ["yt-instrumental", "https://explicit", "--dry-run"]):
            mock_preview.return_value = PreviewReport(source_url="x", after_date=None)
            main()
        assert mock_preview.call_count == 1
        assert mock_preview.call_args.kwargs["url"] == "https://explicit"

    def test_multi_source_artist_override_warns(self, caplog):
        cfg = _make_label_config(sources=[
            Source(url="https://yt.com/a", after_date=None),
            Source(url="https://yt.com/b", after_date=None),
        ])
        with patch("yt_song_to_instrumental.cli.load_label_config", return_value=cfg), \
             patch("yt_song_to_instrumental.cli.preview_url") as mock_preview, \
             patch("yt_song_to_instrumental.cli.HistoryDB"), \
             patch.object(sys, "argv", ["yt-instrumental", "--dry-run", "--artist", "Forced"]):
            mock_preview.return_value = PreviewReport(source_url="x", after_date=None)
            with caplog.at_level("WARNING"):
                main()
        assert any("override" in rec.message for rec in caplog.records)

    def test_run_calls_process_url_per_source(self):
        cfg = _make_label_config(sources=[
            Source(url="https://yt.com/a", after_date=None),
        ])
        with patch("yt_song_to_instrumental.cli.load_label_config", return_value=cfg), \
             patch("yt_song_to_instrumental.cli.process_url") as mock_process, \
             patch("yt_song_to_instrumental.cli.HistoryDB"), \
             patch.object(sys, "argv", ["yt-instrumental", "--skip-upload"]):
            mock_process.return_value = PipelineReport()
            main()
        assert mock_process.call_count == 1
        assert mock_process.call_args.kwargs["url"] == "https://yt.com/a"


class TestPipelineReportPrint:
    def test_upload_url_appears_when_id_present(self, capsys):
        report = PipelineReport(uploaded=1)
        report.tracks.append(TrackReport(
            video_id="src123",
            title="raw",
            artist="Nyte Vandal",
            status="uploaded",
            rendered_title="Nyte Vandal — velvetine (Instrumental)",
            youtube_upload_id="atIHN71j8Mw",
        ))
        _print_pipeline_report(report)
        out = capsys.readouterr().out
        assert "Nyte Vandal — velvetine (Instrumental)" in out
        assert "→ https://youtu.be/atIHN71j8Mw" in out

    def test_no_url_when_no_upload_id(self, capsys):
        report = PipelineReport(failed=1)
        report.tracks.append(TrackReport(
            video_id="src123",
            title="raw",
            artist="Nyte Vandal",
            status="upload_failed",
            reason="quota",
        ))
        _print_pipeline_report(report)
        out = capsys.readouterr().out
        assert "https://youtu.be/" not in out
        assert "[upload_failed (quota)] Nyte Vandal — raw" in out


class TestConfig:
    def test_loads_config_from_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SEPARATOR_MODEL", "mdxnet")
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "out"))
        monkeypatch.setenv("TMP_DIR", str(tmp_path / "tmp"))
        monkeypatch.setenv("DB_PATH", ":memory:")

        from yt_song_to_instrumental.config import AppConfig
        config = AppConfig()
        assert config.separator_model == "mdxnet"
