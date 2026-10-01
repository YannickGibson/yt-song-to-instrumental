#!/usr/bin/env python3
"""Single-worker macOS supervisor with durable recovery and shared flock admission."""
import argparse
from datetime import datetime, timedelta
import fcntl
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import time
from zoneinfo import ZoneInfo

from yt_song_to_instrumental import constants as C
from yt_song_to_instrumental.constants import RUNTIME_DEFAULTS

ZONE = None


def load_config(path):
    config = dict(RUNTIME_DEFAULTS)
    config.update(json.loads(path.read_text()))
    project = Path(config[C.RUNTIME_PROJECT])
    worker_python = Path(config[C.RUNTIME_COMMAND][C.RUNTIME_NUMBER_0])
    if (project / C.RUNTIME_VENV).resolve() == worker_python.parent.parent.resolve():
        raise ValueError(C.RUNTIME_ENVIRONMENT_ERROR)
    return config



def write_json(path, value):
    temporary = path.with_suffix(path.suffix + C.RUNTIME_TMP)
    with temporary.open(C.RUNTIME_TEXT_WRITE_MODE) as stream:
        json.dump(value, stream, indent=C.RUNTIME_NUMBER_2, sort_keys=True)
        stream.write(C.RUNTIME_NEWLINE)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temporary, C.RUNTIME_PRIVATE_FILE_MODE)
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def due_date(now, hour, minute):
    if (now.hour, now.minute) < (hour, minute):
        now -= timedelta(days=C.RUNTIME_NUMBER_1)
    return now.date().isoformat()


def pending_requests(path):
    if not path.is_file():
        raise FileNotFoundError(C.RUNTIME_DATABASE_MISSING_ERROR)
    with sqlite3.connect(path.as_uri() + C.RUNTIME_MODE_RO, uri=True, timeout=C.RUNTIME_NUMBER_15) as db:
        return [list(row) for row in db.execute(
            C.RUNTIME_PENDING_REQUESTS_QUERY)]


def lock_file(path, blocking=False):
    path.parent.mkdir(parents=True, exist_ok=True, mode=C.RUNTIME_PRIVATE_DIRECTORY_MODE)
    stream = path.open(C.RUNTIME_LOCK_OPEN_MODE)
    try:
        fcntl.flock(stream, fcntl.LOCK_EX | (C.RUNTIME_NUMBER_0 if blocking else fcntl.LOCK_NB))
    except BlockingIOError:
        stream.close()
        return None
    return stream


def event(kind, **details):
    print(json.dumps({C.RUNTIME_TIME: datetime.now(ZONE).isoformat(), C.RUNTIME_EVENT: kind, **details}), flush=True)


def backup_databases(config, state, now):
    due = due_date(now, *config[C.RUNTIME_BACKUP_TIME])
    if state.get(C.RUNTIME_BACKUP_DATE) == due or time.time() < (state.get(C.RUNTIME_BACKUP_RETRY_AFTER) or C.RUNTIME_NUMBER_0):
        return
    folder = Path(config[C.RUNTIME_RUNTIME_DIR]) / C.RUNTIME_BACKUPS
    folder.mkdir(parents=True, exist_ok=True, mode=C.RUNTIME_PRIVATE_DIRECTORY_MODE)
    for index, source_name in enumerate(config[C.RUNTIME_BACKUP_DATABASES]):
        source = Path(source_name)
        if not source.is_file():
            continue
        destination = folder / f"{index}-{source.stem}-{due}.db"
        temporary = destination.with_suffix(C.RUNTIME_PARTIAL)
        with sqlite3.connect(source.as_uri() + C.RUNTIME_MODE_RO, uri=True, timeout=C.RUNTIME_NUMBER_15) as src:
            with sqlite3.connect(temporary) as dst:
                src.backup(dst)
                if dst.execute(C.RUNTIME_PRAGMA_QUICK_CHECK).fetchone()[C.RUNTIME_NUMBER_0] != C.RUNTIME_OK:
                    raise RuntimeError(C.RUNTIME_BACKUP_INTEGRITY_CHECK_FAILED)
        os.chmod(temporary, C.RUNTIME_PRIVATE_FILE_MODE)
        os.replace(temporary, destination)
        for old in sorted(folder.glob(f"{index}-{source.stem}-*.db"), reverse=True)[config[C.RUNTIME_BACKUP_RETENTION]:]:
            old.unlink()
    state[C.RUNTIME_BACKUP_DATE] = due
    state[C.RUNTIME_BACKUP_RETRY_AFTER] = C.RUNTIME_NUMBER_0
    event(C.RUNTIME_BACKUPS_COMPLETE, date=due)


def retry_delay(config, state):
    failures = state.get(C.RUNTIME_CONSECUTIVE_FAILURES) or C.RUNTIME_NUMBER_0
    return min(config[C.RUNTIME_RETRY_MAX_SECONDS], config[C.RUNTIME_RETRY_SECONDS] * C.RUNTIME_NUMBER_2 ** min(failures, C.RUNTIME_NUMBER_10))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(C.RUNTIME_CONFIG, type=Path, required=True)
    args = parser.parse_args()
    os.umask(C.RUNTIME_UMASK_VALUE)
    global ZONE
    config = load_config(args.config)
    ZONE = ZoneInfo(config[C.RUNTIME_TIMEZONE])
    root = Path(config[C.RUNTIME_RUNTIME_DIR])
    root.mkdir(parents=True, exist_ok=True, mode=C.RUNTIME_PRIVATE_DIRECTORY_MODE)
    supervisor_lock = lock_file(root / C.RUNTIME_SUPERVISOR_LOCK)
    if supervisor_lock is None:
        event(C.RUNTIME_SUPERVISOR_ALREADY_RUNNING)
        return
    state_path = root / C.RUNTIME_STATE_JSON
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    recovery = bool(state.get(C.RUNTIME_JOB_RUNNING) or state.get(C.RUNTIME_RECOVERY_REQUIRED))
    state.update({C.RUNTIME_SUPERVISOR_PID: os.getpid(), C.RUNTIME_SUPERVISOR_STARTED: datetime.now(ZONE).isoformat(),
                  C.RUNTIME_JOB_RUNNING: False, C.RUNTIME_WORKER_PID: None, C.RUNTIME_RECOVERY_REQUIRED: recovery})
    pause = Path(config[C.RUNTIME_PAUSE_FILE])
    worker_lock_path = Path(config[C.RUNTIME_WORKER_LOCK])
    database = Path(config[C.RUNTIME_DATABASE])
    stop = False
    child = None

    def shutdown(_signum, _frame):
        nonlocal stop
        stop = True
        if child is not None and child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    event(C.RUNTIME_SUPERVISOR_STARTED, recovery_required=recovery)
    while not stop:
        now = datetime.now(ZONE)
        state[C.RUNTIME_HEARTBEAT] = now.isoformat()
        state[C.RUNTIME_PAUSED] = pause.exists()
        if state.get(C.RUNTIME_ATTEMPT_DAY) != now.date().isoformat():
            state.update({C.RUNTIME_ATTEMPT_DAY: now.date().isoformat(), C.RUNTIME_CONSECUTIVE_FAILURES: C.RUNTIME_NUMBER_0})
        reset = root / C.RUNTIME_RESET_RETRIES
        if reset.exists():
            reset.unlink()
            state.update({C.RUNTIME_CONSECUTIVE_FAILURES: C.RUNTIME_NUMBER_0, C.RUNTIME_RETRY_AFTER: C.RUNTIME_NUMBER_0})
        try:
            backup_databases(config, state, now)
        except Exception as exc:
            state[C.RUNTIME_BACKUP_RETRY_AFTER] = time.time() + C.RUNTIME_NUMBER_300
            event(C.RUNTIME_BACKUP_FAILED, error_type=type(exc).__name__)
        try:
            pending = pending_requests(database)
            state[C.RUNTIME_PENDING_REQUEST_COUNT] = len(pending)
            due = due_date(now, *config[C.RUNTIME_DAILY_TIME])
            should_run = bool(pending or recovery or (root / C.RUNTIME_RUN_NOW).exists()
                              or state.get(C.RUNTIME_DAILY_SUCCESS_DATE) != due
                              or time.time() >= (state.get(C.RUNTIME_NEXT_RUN_AFTER) or C.RUNTIME_NUMBER_0))
            allowed = (not pause.exists() and should_run
                       and time.time() >= (state.get(C.RUNTIME_RETRY_AFTER) or C.RUNTIME_NUMBER_0))
            worker_lock = lock_file(worker_lock_path) if allowed else None
            if worker_lock is not None:
                try:
                    if pause.exists() or stop:
                        continue
                    trigger = root / C.RUNTIME_RUN_NOW
                    if trigger.exists():
                        trigger.unlink()
                    log_path = Path(config[C.RUNTIME_WORKER_LOG])
                    if log_path.exists() and log_path.stat().st_size > config[C.RUNTIME_MAX_LOG_BYTES]:
                        os.replace(log_path, log_path.with_name(C.RUNTIME_WORKER_PREVIOUS_LOG))
                    state.update({C.RUNTIME_JOB_RUNNING: True, C.RUNTIME_JOB_STARTED: now.isoformat(),
                                  C.RUNTIME_JOB_DUE_DATE: due, C.RUNTIME_WORKER_PID: None})
                    write_json(state_path, state)
                    environment = dict(os.environ)
                    environment.update(config[C.RUNTIME_ENVIRONMENT])
                    environment[C.RUNTIME_DB_PATH] = str(database)
                    environment[C.RUNTIME_YT_COMMENT_GATE] = str(worker_lock_path)
                    environment[C.RUNTIME_YT_UPLOADER_REPO] = config[C.RUNTIME_PROJECT]
                    log_path.parent.mkdir(parents=True, exist_ok=True, mode=C.RUNTIME_PRIVATE_DIRECTORY_MODE)
                    with log_path.open(C.RUNTIME_LOG_OPEN_MODE) as log:
                        child = subprocess.Popen(config[C.RUNTIME_COMMAND], cwd=config[C.RUNTIME_PROJECT],
                            env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                            pass_fds=(worker_lock.fileno(),), start_new_session=True)
                        state[C.RUNTIME_WORKER_PID] = child.pid
                        write_json(state_path, state)
                        event(C.RUNTIME_PIPELINE_STARTED, pid=child.pid, daily_due=due,
                              pending_count=len(pending))
                        while child.poll() is None:
                            state[C.RUNTIME_HEARTBEAT] = datetime.now(ZONE).isoformat()
                            state[C.RUNTIME_PAUSED] = pause.exists()
                            write_json(state_path, state)
                            if stop:
                                try:
                                    child.wait(timeout=config[C.RUNTIME_SHUTDOWN_SECONDS])
                                except subprocess.TimeoutExpired:
                                    os.killpg(child.pid, signal.SIGKILL)
                            time.sleep(config[C.RUNTIME_HEARTBEAT_SECONDS])
                        returncode = child.returncode
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    child = None
                    remaining = pending_requests(database)
                    unchanged_pending = bool(remaining and remaining == pending)
                    success = returncode == C.RUNTIME_NUMBER_0 and not remaining and not stop
                    recovery = not success
                    state.update({C.RUNTIME_JOB_RUNNING: False, C.RUNTIME_WORKER_PID: None,
                                  C.RUNTIME_JOB_FINISHED: datetime.now(ZONE).isoformat(),
                                  C.RUNTIME_LAST_RETURNCODE: returncode, C.RUNTIME_RECOVERY_REQUIRED: recovery})
                    if success:
                        state.update({C.RUNTIME_DAILY_SUCCESS_DATE: due, C.RUNTIME_CONSECUTIVE_FAILURES: C.RUNTIME_NUMBER_0,
                                      C.RUNTIME_RETRY_AFTER: C.RUNTIME_NUMBER_0, C.RUNTIME_NEXT_RUN_AFTER: time.time() + config[C.RUNTIME_RESCAN_SECONDS]})
                        recovery = False
                    else:
                        state[C.RUNTIME_CONSECUTIVE_FAILURES] = (state.get(C.RUNTIME_CONSECUTIVE_FAILURES) or C.RUNTIME_NUMBER_0) + C.RUNTIME_NUMBER_1
                        state[C.RUNTIME_RETRY_AFTER] = time.time() + retry_delay(config, state)
                    event(C.RUNTIME_PIPELINE_FINISHED, returncode=returncode,
                          unchanged_pending=unchanged_pending, success=success)
                finally:
                    worker_lock.close()
            state[C.RUNTIME_RECOVERY_REQUIRED] = recovery
        except Exception as exc:
            recovery = True
            state[C.RUNTIME_RECOVERY_REQUIRED] = True
            state[C.RUNTIME_LAST_SUPERVISOR_ERROR] = type(exc).__name__
            state[C.RUNTIME_RETRY_AFTER] = time.time() + retry_delay(config, state)
            event(C.RUNTIME_SUPERVISOR_ITERATION_FAILED, error_type=type(exc).__name__)
        write_json(state_path, state)
        for _ in range(config[C.RUNTIME_POLL_SECONDS]):
            if stop:
                break
            time.sleep(C.RUNTIME_NUMBER_1)
    state.update({C.RUNTIME_SUPERVISOR_PID: None, C.RUNTIME_SUPERVISOR_STOPPED: datetime.now(ZONE).isoformat()})
    write_json(state_path, state)
    supervisor_lock.close()


if __name__ == C.RUNTIME_MAIN:
    main()
