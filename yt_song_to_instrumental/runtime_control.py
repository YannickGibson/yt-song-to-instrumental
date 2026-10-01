"""Control the one managed worker without launching a parallel pipeline."""
import argparse
import json
import os
from pathlib import Path

from yt_song_to_instrumental import constants as C
from yt_song_to_instrumental.runtime import load_config, lock_file
from yt_song_to_instrumental.runtime_install import install, service_action


def control(config_path, action, system=False):
    os.umask(C.RUNTIME_UMASK_VALUE)
    config = load_config(config_path)
    root = Path(config[C.RUNTIME_RUNTIME_DIR])
    if action != C.RUNTIME_INSTALL:
        root.mkdir(parents=True, exist_ok=True, mode=C.RUNTIME_PRIVATE_DIRECTORY_MODE)
    pause = Path(config[C.RUNTIME_PAUSE_FILE])
    if action == C.RUNTIME_INSTALL:
        install(config_path, system)
    elif action in (C.RUNTIME_START, C.RUNTIME_STOP):
        service_action(config, action, system)
    elif action == C.RUNTIME_PAUSE:
        pause.parent.mkdir(parents=True, exist_ok=True, mode=C.RUNTIME_PRIVATE_DIRECTORY_MODE)
        pause.touch(mode=C.RUNTIME_PRIVATE_FILE_MODE)
    elif action == C.RUNTIME_RESUME:
        pause.unlink(missing_ok=True)
        (root / C.RUNTIME_RESET_RETRIES).touch(mode=C.RUNTIME_PRIVATE_FILE_MODE)
    elif action == C.RUNTIME_RUN_NOW:
        (root / C.RUNTIME_RUN_NOW).touch(mode=C.RUNTIME_PRIVATE_FILE_MODE)
        (root / C.RUNTIME_RESET_RETRIES).touch(mode=C.RUNTIME_PRIVATE_FILE_MODE)
    state_path = root / C.RUNTIME_STATE_JSON
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    state[C.RUNTIME_PAUSED] = pause.exists()
    state[C.RUNTIME_RUN_REQUESTED] = (root / C.RUNTIME_RUN_NOW).exists()
    for name in (C.RUNTIME_SUPERVISOR, C.RUNTIME_WORKER):
        path = root / C.RUNTIME_SUPERVISOR_LOCK if name == C.RUNTIME_SUPERVISOR else Path(config[C.RUNTIME_WORKER_LOCK])
        gate = lock_file(path)
        state[f"{name}_lock_held"] = gate is None
        if gate is not None:
            gate.close()
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(C.RUNTIME_ACTION, choices=(C.RUNTIME_INSTALL, C.RUNTIME_START, C.RUNTIME_STOP, C.RUNTIME_STATUS, C.RUNTIME_PAUSE, C.RUNTIME_RESUME, C.RUNTIME_RUN_NOW))
    parser.add_argument(C.RUNTIME_CONFIG, type=Path, required=True)
    parser.add_argument(C.RUNTIME_SYSTEM_2, action=C.RUNTIME_STORE_TRUE, help=C.RUNTIME_SYSTEM_HELP)
    args = parser.parse_args()
    print(json.dumps(control(args.config, args.action, args.system), indent=C.RUNTIME_NUMBER_2, sort_keys=True))


if __name__ == C.RUNTIME_MAIN:
    main()
