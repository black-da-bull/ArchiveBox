__package__ = 'archivebox.queues'

import sys
import time
import signal
import psutil
import subprocess
from pathlib import Path
from rich.pretty import pprint

from typing import Dict, cast

from supervisor.xmlrpc import SupervisorTransport
from xmlrpc.client import ServerProxy

from .settings import CONFIG_FILE, PID_FILE, SOCK_FILE, LOG_FILE, WORKER_DIR, TMP_DIR, LOGS_DIR


def create_supervisord_config():
    config_content = f"""
[supervisord]
nodaemon = true
environment = IS_SUPERVISORD_PARENT="true"
pidfile = %(here)s/{PID_FILE.name}
logfile = %(here)s/../{LOGS_DIR.name}/{LOG_FILE.name}
childlogdir = %(here)s/../{LOGS_DIR.name}
directory = %(here)s/..
strip_ansi = true
nocleanup = true

[unix_http_server]
file = %(here)s/{SOCK_FILE.name}
chmod = 0700

[supervisorctl]
serverurl = unix://%(here)s/{SOCK_FILE.name}

[rpcinterface:supervisor]
supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

[include]
files = %(here)s/{WORKER_DIR.name}/*.conf

"""
    with open(CONFIG_FILE, "w") as f:
        f.write(config_content)

def create_worker_config(daemon):
    Path.mkdir(WORKER_DIR, exist_ok=True)
    
    name = daemon['name']
    configfile = WORKER_DIR / f"{name}.conf"

    config_content = f"[program:{name}]\n"
    for key, value in daemon.items():
        if key == 'name': continue
        config_content += f"{key}={value}\n"
    config_content += "\n"

    with open(configfile, "w") as f:
        f.write(config_content)


def get_existing_supervisord_process():
    try:
        transport = SupervisorTransport(None, None, f"unix://{SOCK_FILE}")
        server = ServerProxy("http://localhost", transport=transport)
        current_state = cast(Dict[str, int | str], server.supervisor.getState())
        if current_state["statename"] == "RUNNING":
            pid = server.supervisor.getPID()
            print(f"[🦸‍♂️] Supervisord connected (pid={pid}) via unix://{str(SOCK_FILE).replace(str(TMP_DIR), 'tmp')}.")
            return server.supervisor
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"Error connecting to existing supervisord: {str(e)}")
        return None

def stop_existing_supervisord_process():
    try:
        pid = int(PID_FILE.read_text())
    except FileNotFoundError:
        return
    except ValueError:
        PID_FILE.unlink()
        return

    try:
        print(f"[🦸‍♂️] Stopping supervisord process (pid={pid})...")
        proc = psutil.Process(pid)
        proc.terminate()
        proc.wait()
    except Exception:
        pass
    try:
        PID_FILE.unlink()
    except FileNotFoundError:
        pass

def start_new_supervisord_process(daemonize=True):
    print(f"[🦸‍♂️] Supervisord starting{' in background' if daemonize else ''}...")
    # Create a config file in the current working directory
    create_supervisord_config()

    # Start supervisord
    subprocess.Popen(
        f"supervisord --configuration={CONFIG_FILE}",
        stdin=None,
        shell=True,
        start_new_session=daemonize,
    )

    def exit_signal_handler(signum, frame):
        if signum != 13:
            print(f"\n[🦸‍♂️] Supervisord got stop signal ({signal.strsignal(signum)}). Terminating child processes...")
        stop_existing_supervisord_process()
        raise SystemExit(0)

    # Monitor for termination signals and cleanup child processes
    if not daemonize:
        signal.signal(signal.SIGINT, exit_signal_handler)
        signal.signal(signal.SIGHUP, exit_signal_handler)
        signal.signal(signal.SIGPIPE, exit_signal_handler)
        signal.signal(signal.SIGTERM, exit_signal_handler)
    # otherwise supervisord will containue in background even if parent proc is ends (aka daemon mode)

    time.sleep(2)

    return get_existing_supervisord_process()

def get_or_create_supervisord_process(daemonize=True):
    supervisor = get_existing_supervisord_process()
    if supervisor is None:
        stop_existing_supervisord_process()
        supervisor = start_new_supervisord_process(daemonize=daemonize)

    assert supervisor and supervisor.getPID(), "Failed to start supervisord or connect to it!"
    return supervisor

def start_worker(supervisor, daemon, lazy=False):
    assert supervisor.getPID()

    print(f"[🦸‍♂️] Supervisord starting new subprocess worker: {daemon['name']}...")
    create_worker_config(daemon)

    result = supervisor.reloadConfig()
    added, changed, removed = result[0]
    # print(f"Added: {added}, Changed: {changed}, Removed: {removed}")
    for removed in removed:
        supervisor.stopProcessGroup(removed)
        supervisor.removeProcessGroup(removed)
    for changed in changed:
        supervisor.stopProcessGroup(changed)
        supervisor.removeProcessGroup(changed)
        supervisor.addProcessGroup(changed)
    for added in added:
        supervisor.addProcessGroup(added)

    time.sleep(1)

    for _ in range(10):
        procs = supervisor.getAllProcessInfo()
        for proc in procs:
            if proc['name'] == daemon["name"]:
                # See process state diagram here: http://supervisord.org/subprocess.html
                if proc['statename'] == 'RUNNING':
                    print(f"     - Worker {daemon['name']}: already {proc['statename']} ({proc['description']})")
                    return proc
                else:
                    if not lazy:
                        supervisor.startProcessGroup(daemon["name"], True)
                    proc = supervisor.getProcessInfo(daemon["name"])
                    print(f"     - Worker {daemon['name']}: started {proc['statename']} ({proc['description']})")
                return proc

        # retry in a second in case it's slow to launch
        time.sleep(0.5)

    raise Exception(f"Failed to start worker {daemon['name']}! Only found: {procs}")


def watch_worker(supervisor, daemon_name, interval=5):
    """loop continuously and monitor worker's health"""
    while True:
        proc = get_worker(supervisor, daemon_name)
        if not proc:
            raise Exception("Worker dissapeared while running! " + daemon_name)

        if proc['statename'] == 'STOPPED':
            return proc

        if proc['statename'] == 'RUNNING':
            time.sleep(1)
            continue

        if proc['statename'] in ('STARTING', 'BACKOFF', 'FATAL', 'EXITED', 'STOPPING'):
            print(f'[🦸‍♂️] WARNING: Worker {daemon_name} {proc["statename"]} {proc["description"]}')
            time.sleep(interval)
            continue


def get_worker(supervisor, daemon_name):
    try:
        return supervisor.getProcessInfo(daemon_name)
    except Exception:
        pass
    return None

def stop_worker(supervisor, daemon_name):
    proc = get_worker(supervisor, daemon_name)

    for _ in range(10):
        if not proc:
            # worker does not exist (was never running or configured in the first place)
            return True
        
        # See process state diagram here: http://supervisord.org/subprocess.html
        if proc['statename'] == 'STOPPED':
            # worker was configured but has already stopped for some reason
            supervisor.removeProcessGroup(daemon_name)
            return True
        else:
            # worker was configured and is running, stop it now
            supervisor.stopProcessGroup(daemon_name)

        # wait 500ms and then re-check to make sure it's really stopped
        time.sleep(0.5)
        proc = get_worker(supervisor, daemon_name)

    raise Exception(f"Failed to stop worker {daemon_name}!")

def main(daemons):
    supervisor = get_or_create_supervisord_process(daemonize=True)

    worker = start_worker(supervisor, daemons["webworker"])
    pprint(worker)

    print("All processes started in background.")
    
    # Optionally you can block the main thread until an exit signal is received:
    # try:
    #     signal.pause()
    # except KeyboardInterrupt:
    #     pass
    # finally:
    #     stop_existing_supervisord_process()

# if __name__ == "__main__":

#     DAEMONS = {
#         "webworker": {
#             "name": "webworker",
#             "command": "python3 -m http.server 9000",
#             "directory": str(cwd),
#             "autostart": "true",
#             "autorestart": "true",
#             "stdout_logfile": cwd / "webworker.log",
#             "stderr_logfile": cwd / "webworker_error.log",
#         },
#     }
#     main(DAEMONS, cwd)
