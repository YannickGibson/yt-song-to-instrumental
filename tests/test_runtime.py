import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from yt_song_to_instrumental import runtime, runtime_install
from yt_song_to_instrumental.constants import RUNTIME_DEFAULTS
from yt_song_to_instrumental.history import HistoryDB
from yt_song_to_instrumental.runtime_control import control


def wait_until(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(.05)
    raise AssertionError("Managed process did not reach expected state")


@pytest.fixture
def deployment(tmp_path):
    database = tmp_path / "history.db"
    HistoryDB(database).close()
    worker = tmp_path / "worker.py"
    worker.write_text("import time\ntime.sleep(60)\n")
    config = dict(RUNTIME_DEFAULTS, project=str(tmp_path), runtime_dir=str(tmp_path),
                  command=[sys.executable, str(worker)], database=str(database),
                  pause_file=str(tmp_path / "paused"), worker_lock=str(tmp_path / "worker.lock"),
                  worker_log=str(tmp_path / "worker.log"), backup_databases=[str(database)],
                  environment={"PYTHONPATH": str(Path.cwd())}, poll_seconds=1, heartbeat_seconds=.05,
                  retry_seconds=.05, retry_max_seconds=.1, shutdown_seconds=1,
                  label="local.example-worker", username="example")
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    processes = []

    def start():
        process = subprocess.Popen([sys.executable, "-m", "yt_song_to_instrumental.runtime", "--config", str(path)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        processes.append(process)
        return process

    yield config, path, worker, start
    for process in processes:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        process.stderr.close()
    state_path = tmp_path / "state.json"
    if state_path.exists():
        pid = json.loads(state_path.read_text()).get("worker_pid")
        if pid:
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def read_state(config):
    path = Path(config["runtime_dir"]) / "state.json"
    return json.loads(path.read_text()) if path.exists() else {}


def test_calendar_boundary():
    assert runtime.due_date(datetime(2026, 1, 2, 6, 4), 6, 5) == "2026-01-01"
    assert runtime.due_date(datetime(2026, 1, 2, 6, 5), 6, 5) == "2026-01-02"


def test_lock_excludes_other_owners(tmp_path):
    path = tmp_path / "worker.lock"
    gate = runtime.lock_file(path)
    assert runtime.lock_file(path) is None
    gate.close()
    runtime.lock_file(path).close()


def test_retry_delay_remains_bounded_after_many_failures():
    assert runtime.retry_delay(RUNTIME_DEFAULTS, {"consecutive_failures": 100}) == 3600


def test_rejects_shared_development_environment(tmp_path):
    env = tmp_path / ".venv-mac"
    env.mkdir()
    (tmp_path / ".venv").symlink_to(env)
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"project": str(tmp_path), "command": [str(env / "bin/python")]}))
    with pytest.raises(ValueError, match="separate"):
        runtime.load_config(path)


def test_run_now_respects_pause_and_does_not_spawn(deployment):
    config, path, _, _ = deployment
    control(path, "pause")
    state = control(path, "run-now")
    assert state["paused"] and state["run_requested"]
    assert not state["worker_lock_held"]


def test_backup_is_consistent_and_private(deployment):
    config, _, _, _ = deployment
    state = {}
    runtime.backup_databases(config, state, datetime(2026, 1, 2, 12, tzinfo=ZoneInfo("UTC")))
    backup = next((Path(config["runtime_dir"]) / "backups").glob("*.db"))
    with sqlite3.connect(backup) as db:
        assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert backup.stat().st_mode & 0o777 == 0o600
    assert state["backup_date"] == "2026-01-02"


def test_single_worker_and_shutdown_recovery(deployment):
    config, _, _, start = deployment
    first = start()
    state = wait_until(lambda: (s if (s := read_state(config)).get("worker_pid") else None))
    second = start()
    assert second.wait(timeout=5) == 0
    assert read_state(config)["worker_pid"] == state["worker_pid"]
    first.terminate()
    first.wait(timeout=5)
    state = read_state(config)
    assert state["recovery_required"] and not state["job_running"]
    assert "daily_success_date" not in state
    runtime.lock_file(Path(config["worker_lock"])).close()


def test_orphan_holds_gate_after_supervisor_crash(deployment):
    config, path, worker, start = deployment
    first = start()
    pid = wait_until(lambda: read_state(config).get("worker_pid"))
    first.kill()
    first.wait(timeout=5)
    second = start()
    wait_until(lambda: read_state(config).get("supervisor_pid") == second.pid)
    time.sleep(1.2)
    assert runtime.lock_file(Path(config["worker_lock"])) is None
    os.killpg(pid, signal.SIGTERM)
    new_pid = wait_until(lambda: read_state(config).get("worker_pid"))
    assert new_pid != pid


def test_failure_retries_past_three_attempts_and_never_records_success(deployment):
    config, _, worker, start = deployment
    worker.write_text("raise SystemExit(1)\n")
    start()
    state = wait_until(lambda: (s if (s := read_state(config)).get("consecutive_failures", 0) >= 4 else None))
    assert state["recovery_required"]
    assert "daily_success_date" not in state


def test_saved_recovery_survives_restart_even_after_daily_success(deployment):
    config, _, _, start = deployment
    now = datetime.now(ZoneInfo("UTC"))
    runtime.write_json(Path(config["runtime_dir"]) / "state.json", {
        "recovery_required": True, "daily_success_date": runtime.due_date(now, 6, 5),
        "next_run_after": time.time() + 3600,
    })
    start()
    wait_until(lambda: read_state(config).get("worker_pid"))


def test_success_rescans_and_pending_requests_prevent_false_success(deployment):
    config, path, worker, start = deployment
    worker.write_text("pass\n")
    db = HistoryDB(config["database"])
    db.enqueue_priority_request("https://www.youtube.com/watch?v=Example0001")
    db.close()
    start()
    state = wait_until(lambda: (s if (s := read_state(config)).get("last_returncode") == 0 else None))
    assert state["recovery_required"]
    assert "daily_success_date" not in state


def test_installer_refuses_live_worker_before_touching_service(deployment, monkeypatch):
    config, path, _, _ = deployment
    monkeypatch.setattr(runtime_install, "service_paths", lambda *a: ("gui/1", Path(config["runtime_dir"]) / "service.plist", Mock(pw_uid=1)))
    launchctl = Mock()
    monkeypatch.setattr(runtime_install, "launchctl", launchctl)
    gate = runtime.lock_file(Path(config["worker_lock"]))
    try:
        with pytest.raises(RuntimeError, match="Worker is active"):
            runtime_install.install(path)
        launchctl.assert_not_called()
        assert Path(config["pause_file"]).exists()
    finally:
        gate.close()


def test_definition_uses_package_and_ordinary_daemon_user(deployment):
    config, path, _, _ = deployment
    value = runtime_install.definition(config, path, True)
    assert value["ProgramArguments"][1:3] == ["-m", "yt_song_to_instrumental.runtime"]
    assert value["KeepAlive"] is True
    assert value["UserName"] == "example"


def test_successful_worker_rescans_without_daily_timer(deployment):
    config, path, worker, start = deployment
    config["rescan_seconds"] = .1
    path.write_text(json.dumps(config))
    counter = Path(config["runtime_dir"]) / "runs"
    worker.write_text("from pathlib import Path\np=Path('runs')\np.write_text((p.read_text() if p.exists() else '')+'x')\n")
    start()
    wait_until(lambda: counter.exists() and len(counter.read_text()) >= 2)
    state = read_state(config)
    assert state["daily_success_date"]
    assert not state["recovery_required"]


def test_worker_crash_reaps_descendants_before_releasing_gate(deployment):
    config, _, worker, start = deployment
    worker.write_text("import subprocess,sys\np=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])\nfrom pathlib import Path\nPath('descendant').write_text(str(p.pid))\nraise SystemExit(1)\n")
    start()
    wait_until(lambda: read_state(config).get("last_returncode") == 1)
    pid = int((Path(config["runtime_dir"]) / "descendant").read_text())
    # An exited orphan may briefly remain as a zombie until init reaps it.
    result = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    assert not result.stdout.strip() or result.stdout.strip().startswith("Z")


def test_system_install_assigns_private_files_to_worker_account(deployment, monkeypatch):
    config, path, _, _ = deployment
    root = Path(config["runtime_dir"])
    account = Mock(pw_uid=123, pw_gid=456)
    monkeypatch.setattr(runtime_install, "service_paths", lambda cfg, system=False: ("system" if system else "gui/123", root / ("daemon.plist" if system else "agent.plist"), account))
    monkeypatch.setattr(runtime_install.os, "geteuid", lambda: 0)
    chown = Mock()
    monkeypatch.setattr(runtime_install.os, "chown", chown)
    monkeypatch.setattr(runtime_install, "launchctl", Mock(return_value=Mock(returncode=1)))
    runtime_install.install(path, system=True)
    owned = [call.args[0] for call in chown.call_args_list]
    assert Path(config["worker_lock"]) in owned
    assert root / "supervisor.lock" in owned
    assert Path(config["pause_file"]) in owned
