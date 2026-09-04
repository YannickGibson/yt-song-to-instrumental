import sys
from unittest.mock import MagicMock, patch

import pytest

from yt_song_to_instrumental.cli import _print_pipeline_report, main
from yt_song_to_instrumental.config import LabelConfig, Source
from yt_song_to_instrumental.history import PriorityRequest
from yt_song_to_instrumental.pipeline import PipelineReport, TrackReport
from yt_song_to_instrumental.preview import PreviewReport


def _make_label_config(
    sources: list[Source] | None = None,
    default_model: str | None = None,
) -> LabelConfig:
    data = {
        "channel": {"name": "Test", "description": "T"},
        "label": {"name": "TestLabel"},
        "templates": {
            "video_title": "<artist-name>",
            "video_description": "D",
            "album_playlist_name": "<artist-name> — <album-name>",
            "artist_playlist_name": "<artist-name>",
        },
        "create_playlists_for_collaborators": True,
        "sources": [{"url": s.url, "after_date": s.after_date, "tab": s.tab} for s in (sources or [])],
    }
    if default_model is not None:
        data["default_model"] = default_model
    return LabelConfig(data)


class TestListModels:
    def test_list_models_prints_output(self, capsys):
        with patch.object(sys, "argv", ["yt-instrumental", "--list-models"]):
            main()

        output = capsys.readouterr().out
        assert "htdemucs" in output
        assert "inst_hq_4" in output
        assert "GPU required" in output
        assert "Min memory" in output


class TestArgParsing:
    def test_enqueue_priority_exits_without_loading_label_config(self, capsys):
        request = PriorityRequest(
            id=7,
            url="https://www.youtube.com/watch?v=QueueItem01",
            requested_at="2026-09-05T00:00:00+00:00",
            status="pending",
            started_at=None,
            finished_at=None,
            error="",
        )
        with patch("yt_song_to_instrumental.cli.enqueue_priority_request", return_value=request) as mock_enqueue, \
             patch("yt_song_to_instrumental.cli.load_label_config") as mock_load_label, \
             patch.object(sys, "argv", ["yt-instrumental", "--enqueue-priority", request.url]):
            main()

        assert mock_enqueue.call_args.args[0] == request.url
        mock_load_label.assert_not_called()
        assert "first in queue" in capsys.readouterr().out

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
        monkeypatch.setenv("SEPARATOR_MODEL", "inst_hq_4")
        monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "out"))
        monkeypatch.setenv("TMP_DIR", str(tmp_path / "tmp"))
        monkeypatch.setenv("DB_PATH", ":memory:")

        from yt_song_to_instrumental.config import AppConfig
        config = AppConfig()
        assert config.separator_model == "inst_hq_4"


class TestModelPrecedence:
    """--model (if passed) > label_config.default_model > DEFAULT_MODEL."""

    def test_label_default_used_when_no_cli_model(self):
        cfg = _make_label_config(
            sources=[Source(url="https://yt.com/a", after_date=None)],
            default_model="inst_hq_4",
        )
        with patch("yt_song_to_instrumental.cli.load_label_config", return_value=cfg), \
             patch("yt_song_to_instrumental.cli.process_url") as mock_process, \
             patch("yt_song_to_instrumental.cli.HistoryDB"), \
             patch.object(sys, "argv", ["yt-instrumental", "--skip-upload"]):
            mock_process.return_value = PipelineReport()
            main()
        assert mock_process.call_args.kwargs["model_name"] == "inst_hq_4"

    def test_cli_model_overrides_label_default(self):
        cfg = _make_label_config(
            sources=[Source(url="https://yt.com/a", after_date=None)],
            default_model="inst_hq_4",
        )
        with patch("yt_song_to_instrumental.cli.load_label_config", return_value=cfg), \
             patch("yt_song_to_instrumental.cli.process_url") as mock_process, \
             patch("yt_song_to_instrumental.cli.HistoryDB"), \
             patch.object(sys, "argv", ["yt-instrumental", "--skip-upload", "--model", "htdemucs"]):
            mock_process.return_value = PipelineReport()
            main()
        assert mock_process.call_args.kwargs["model_name"] == "htdemucs"

    def test_falls_back_to_htdemucs_when_neither_set(self):
        cfg = _make_label_config(
            sources=[Source(url="https://yt.com/a", after_date=None)],
        )
        with patch("yt_song_to_instrumental.cli.load_label_config", return_value=cfg), \
             patch("yt_song_to_instrumental.cli.process_url") as mock_process, \
             patch("yt_song_to_instrumental.cli.HistoryDB"), \
             patch.object(sys, "argv", ["yt-instrumental", "--skip-upload"]):
            mock_process.return_value = PipelineReport()
            main()
        assert mock_process.call_args.kwargs["model_name"] == "htdemucs"


class TestTrimPrecedence:
    def test_cli_trim_silence_overrides_config_false(self):
        cfg = _make_label_config(
            sources=[Source(url="https://yt.com/a", after_date=None)],
        )
        # trim_silence is False in config by default
        with patch("yt_song_to_instrumental.cli.load_label_config", return_value=cfg), \
             patch("yt_song_to_instrumental.cli.process_url") as mock_process, \
             patch("yt_song_to_instrumental.cli.HistoryDB"), \
             patch.object(sys, "argv", ["yt-instrumental", "--skip-upload", "--trim-silence"]):
            mock_process.return_value = PipelineReport()
            main()
        assert mock_process.call_args.kwargs["trim_silence"] is True

    def test_cli_no_trim_silence_overrides_config_true(self):
        cfg = _make_label_config(
            sources=[Source(url="https://yt.com/a", after_date=None)],
        )
        cfg.trim_silence = True  # Mock label config having trim_silence = True
        with patch("yt_song_to_instrumental.cli.load_label_config", return_value=cfg), \
             patch("yt_song_to_instrumental.cli.process_url") as mock_process, \
             patch("yt_song_to_instrumental.cli.HistoryDB"), \
             patch.object(sys, "argv", ["yt-instrumental", "--skip-upload", "--no-trim-silence"]):
            mock_process.return_value = PipelineReport()
            main()
        assert mock_process.call_args.kwargs["trim_silence"] is False

    def test_uses_config_default_when_unset_on_cli(self):
        cfg = _make_label_config(
            sources=[Source(url="https://yt.com/a", after_date=None)],
        )
        cfg.trim_silence = True
        with patch("yt_song_to_instrumental.cli.load_label_config", return_value=cfg), \
             patch("yt_song_to_instrumental.cli.process_url") as mock_process, \
             patch("yt_song_to_instrumental.cli.HistoryDB"), \
             patch.object(sys, "argv", ["yt-instrumental", "--skip-upload"]):
            mock_process.return_value = PipelineReport()
            main()
        assert mock_process.call_args.kwargs["trim_silence"] is True


class TestTabPrecedence:
    def test_cli_tab_overrides_url_source(self):
        cfg = _make_label_config(sources=[])
        with patch("yt_song_to_instrumental.cli.load_label_config", return_value=cfg), \
             patch("yt_song_to_instrumental.cli.preview_url") as mock_preview, \
             patch("yt_song_to_instrumental.cli.HistoryDB"), \
             patch.object(sys, "argv", ["yt-instrumental", "https://yt.com/c", "--dry-run", "--tab", "releases"]):
            mock_preview.return_value = PreviewReport(source_url="x", after_date=None)
            main()
        assert mock_preview.call_args.kwargs["tab"] == "releases"

    def test_source_tab_used_by_default(self):
        cfg = _make_label_config(
            sources=[Source(url="https://yt.com/a", after_date=None, tab="releases")],
        )
        with patch("yt_song_to_instrumental.cli.load_label_config", return_value=cfg), \
             patch("yt_song_to_instrumental.cli.preview_url") as mock_preview, \
             patch("yt_song_to_instrumental.cli.HistoryDB"), \
             patch.object(sys, "argv", ["yt-instrumental", "--dry-run"]):
            mock_preview.return_value = PreviewReport(source_url="x", after_date=None)
            main()
        assert mock_preview.call_args.kwargs["tab"] == "releases"


class TestShortsCliPrecedence:
    def test_cli_upload_short_sets_config(self):
        cfg = _make_label_config(sources=[Source(url="https://yt.com/a", after_date=None)])
        cfg.upload_short = False
        cfg.upload_short_if_music_video = False
        with patch("yt_song_to_instrumental.cli.load_label_config", return_value=cfg), \
             patch("yt_song_to_instrumental.cli.process_url") as mock_process, \
             patch("yt_song_to_instrumental.cli.HistoryDB"), \
             patch.object(sys, "argv", ["yt-instrumental", "--skip-upload", "--upload-short"]):
            mock_process.return_value = PipelineReport()
            main()
        assert cfg.upload_short is True
        assert cfg.upload_short_if_music_video is False

    def test_cli_upload_short_if_music_video_sets_config(self):
        cfg = _make_label_config(sources=[Source(url="https://yt.com/a", after_date=None)])
        cfg.upload_short = True
        cfg.upload_short_if_music_video = False
        with patch("yt_song_to_instrumental.cli.load_label_config", return_value=cfg), \
             patch("yt_song_to_instrumental.cli.process_url") as mock_process, \
             patch("yt_song_to_instrumental.cli.HistoryDB"), \
             patch.object(sys, "argv", ["yt-instrumental", "--skip-upload", "--upload-short-if-music-video"]):
            mock_process.return_value = PipelineReport()
            main()
        assert cfg.upload_short is False
        assert cfg.upload_short_if_music_video is True

    def test_cli_no_upload_short_disables_shorts(self):
        cfg = _make_label_config(sources=[Source(url="https://yt.com/a", after_date=None)])
        cfg.upload_short_if_music_video = True
        with patch("yt_song_to_instrumental.cli.load_label_config", return_value=cfg), \
             patch("yt_song_to_instrumental.cli.process_url") as mock_process, \
             patch("yt_song_to_instrumental.cli.HistoryDB"), \
             patch.object(sys, "argv", ["yt-instrumental", "--skip-upload", "--no-upload-short"]):
            mock_process.return_value = PipelineReport()
            main()
        assert cfg.upload_short is False
        assert cfg.upload_short_if_music_video is False

    def test_cli_both_short_flags_errors(self):
        cfg = _make_label_config(sources=[Source(url="https://yt.com/a", after_date=None)])
        with patch("yt_song_to_instrumental.cli.load_label_config", return_value=cfg), \
             patch.object(sys, "argv", ["yt-instrumental", "--upload-short", "--upload-short-if-music-video"]):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 2

    def test_cli_shorts_only_passed_to_process_url(self):
        cfg = _make_label_config(sources=[Source(url="https://yt.com/a", after_date=None)])
        with patch("yt_song_to_instrumental.cli.load_label_config", return_value=cfg), \
             patch("yt_song_to_instrumental.cli.process_url") as mock_process, \
             patch("yt_song_to_instrumental.cli.HistoryDB"), \
             patch.object(sys, "argv", ["yt-instrumental", "--skip-upload", "--shorts-only"]):
            mock_process.return_value = PipelineReport()
            main()
        assert mock_process.call_args.kwargs["shorts_only"] is True
