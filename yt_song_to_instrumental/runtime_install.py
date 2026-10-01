"""Install or replace a launchd service only while its worker gate is idle."""
import os
from pathlib import Path
import plistlib
import pwd
import re
import subprocess
import time

from yt_song_to_instrumental import constants as C
from yt_song_to_instrumental.runtime import load_config, lock_file


def service_paths(config, system=False):
    account = pwd.getpwnam(config[C.RUNTIME_USERNAME])
    label = config[C.RUNTIME_LABEL]
    if not re.fullmatch(C.RUNTIME_LABEL_PATTERN, label) or account.pw_uid == C.RUNTIME_NUMBER_0:
        raise ValueError(C.RUNTIME_ACCOUNT_ERROR)
    domain = C.RUNTIME_SYSTEM if system else f"gui/{account.pw_uid}"
    directory = Path(C.RUNTIME_LIBRARY_LAUNCHDAEMONS) if system else Path(account.pw_dir) / C.RUNTIME_LIBRARY_LAUNCHAGENTS
    return domain, directory / f"{label}.plist", account


def definition(config, config_path, system=False):
    root = Path(config[C.RUNTIME_RUNTIME_DIR])
    value = {
        C.RUNTIME_PLIST_LABEL: config[C.RUNTIME_LABEL],
        C.RUNTIME_PROGRAMARGUMENTS: [config[C.RUNTIME_COMMAND][C.RUNTIME_NUMBER_0], C.RUNTIME_M, C.RUNTIME_YT_SONG_TO_INSTRUMENTAL_RUNTIME, C.RUNTIME_CONFIG, str(config_path.absolute())],
        C.RUNTIME_WORKINGDIRECTORY: config[C.RUNTIME_PROJECT], C.RUNTIME_RUNATLOAD: True,
        C.RUNTIME_KEEPALIVE: True, C.RUNTIME_THROTTLEINTERVAL: config[C.RUNTIME_POLL_SECONDS],
        C.RUNTIME_EXITTIMEOUT: config[C.RUNTIME_SHUTDOWN_SECONDS] + config[C.RUNTIME_HEARTBEAT_SECONDS] + C.RUNTIME_NUMBER_5,
        C.RUNTIME_UMASK: C.RUNTIME_UMASK_VALUE, C.RUNTIME_ENVIRONMENTVARIABLES: config[C.RUNTIME_ENVIRONMENT],
        C.RUNTIME_STANDARDOUTPATH: str(root / C.RUNTIME_SUPERVISOR_LOG),
        C.RUNTIME_STANDARDERRORPATH: str(root / C.RUNTIME_SUPERVISOR_ERROR_LOG),
    }
    if system:
        value[C.RUNTIME_PLIST_USERNAME] = config[C.RUNTIME_USERNAME]
    return value


def launchctl(*arguments, check=True):
    return subprocess.run([C.RUNTIME_BIN_LAUNCHCTL, *arguments], check=check, capture_output=True, text=True)


def install(config_path, system=False):
    config = load_config(config_path)
    domain, target, account = service_paths(config, system)
    if system and os.geteuid() != C.RUNTIME_NUMBER_0:
        raise PermissionError(C.RUNTIME_ADMIN_ERROR)
    root = Path(config[C.RUNTIME_RUNTIME_DIR])
    root_existed = root.exists()
    root.mkdir(parents=True, exist_ok=True, mode=C.RUNTIME_PRIVATE_DIRECTORY_MODE)
    if system and not root_existed:
        os.chown(root, account.pw_uid, account.pw_gid)
    pause = Path(config[C.RUNTIME_PAUSE_FILE])
    pause_parent_existed = pause.parent.exists()
    pause.parent.mkdir(parents=True, exist_ok=True, mode=C.RUNTIME_PRIVATE_DIRECTORY_MODE)
    if system and not pause_parent_existed:
        os.chown(pause.parent, account.pw_uid, account.pw_gid)
    already_paused = pause.exists()
    pause.touch(mode=C.RUNTIME_PRIVATE_FILE_MODE)
    worker_lock_path = Path(config[C.RUNTIME_WORKER_LOCK])
    lock_parent_existed = worker_lock_path.parent.exists()
    gate = lock_file(worker_lock_path)
    if system:
        os.chown(pause, account.pw_uid, account.pw_gid)
        os.chown(worker_lock_path, account.pw_uid, account.pw_gid)
        if not lock_parent_existed:
            os.chown(worker_lock_path.parent, account.pw_uid, account.pw_gid)
    if gate is None:
        raise RuntimeError(C.RUNTIME_ACTIVE_WORKER_ERROR)
    try:
        # Remove either prior service domain before installing. Holding the gate
        # prevents an old supervisor from admitting work during the handoff.
        for old_domain in (f"gui/{account.pw_uid}", C.RUNTIME_SYSTEM):
            old_target = f"{old_domain}/{config[C.RUNTIME_LABEL]}"
            if launchctl(C.RUNTIME_PRINT, old_target, check=False).returncode == C.RUNTIME_NUMBER_0:
                launchctl(C.RUNTIME_BOOTOUT, old_target)
        deadline = time.monotonic() + config[C.RUNTIME_SHUTDOWN_SECONDS] + config[C.RUNTIME_POLL_SECONDS]
        while True:
            supervisor_gate = lock_file(root / C.RUNTIME_SUPERVISOR_LOCK)
            if supervisor_gate is not None:
                if system:
                    os.chown(root / C.RUNTIME_SUPERVISOR_LOCK, account.pw_uid, account.pw_gid)
                supervisor_gate.close()
                break
            if time.monotonic() >= deadline:
                raise RuntimeError(C.RUNTIME_HANDOFF_TIMEOUT_ERROR)
            time.sleep(C.RUNTIME_NUMBER_1)
        for old_system in (False, True):
            _, old_path, _ = service_paths(config, old_system)
            if old_path != target and old_path.exists():
                old_path.rename(old_path.with_suffix(C.RUNTIME_PLIST_DISABLED))
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(C.RUNTIME_PLIST_TMP)
        with temporary.open(C.RUNTIME_BINARY_WRITE_MODE) as stream:
            plistlib.dump(definition(config, config_path, system), stream)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(C.RUNTIME_DAEMON_FILE_MODE if system else C.RUNTIME_PRIVATE_FILE_MODE)
        os.replace(temporary, target)
        launchctl(C.RUNTIME_BOOTSTRAP, domain, str(target))
        if not already_paused:
            pause.unlink(missing_ok=True)
    finally:
        gate.close()


def service_action(config, action, system=False):
    domain, path, _ = service_paths(config, system)
    target = f"{domain}/{config[C.RUNTIME_LABEL]}"
    if action == C.RUNTIME_STOP:
        launchctl(C.RUNTIME_BOOTOUT, target)
    elif launchctl(C.RUNTIME_PRINT, target, check=False).returncode != C.RUNTIME_NUMBER_0:
        launchctl(C.RUNTIME_BOOTSTRAP, domain, str(path))
