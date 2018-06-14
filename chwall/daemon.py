#!/usr/bin/env python3

import os
import sys
import time
import yaml
import signal


# chwall imports
from chwall.utils import BASE_CACHE_PATH, read_config
from chwall.wallpaper import build_wallpapers_list, choose_wallpaper


def kill_daemon(_signo, _stack_frame):
    sys.exit(0)


def daemon_loop(config):
    sleep_time = config['general']['sleep']
    error_code = 0
    try:
        signal.signal(signal.SIGTERM, kill_daemon)
        while True:
            # Silently ignore failures
            pick_wallpaper(config)
            time.sleep(sleep_time)
    except (KeyboardInterrupt, SystemExit):
        print("Exit signal received")
    except Exception as e:
        print("{}: {}".format(type(e).__name__, e), file=sys.stderr)
        error_code = 1
    finally:
        print("Cleaning up…")
        os.unlink("{}/roadmap".format(BASE_CACHE_PATH))
        if error_code == 0:
            print("Kthxbye!")
        return error_code


def daemon():
    newpid = os.fork()
    if newpid != 0:
        print("Start loop")
        return 0
    # In the forked process
    config = read_config()
    data = build_wallpapers_list(config)
    data["chwall_pid"] = os.getpid()
    with open("{}/roadmap".format(BASE_CACHE_PATH), "w") as f:
        yaml.dump(data, f, explicit_start=True, default_flow_style=False)
    return daemon_loop(config)


if __name__ == "__main__":
    sys.exit(daemon())
