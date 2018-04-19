#!/usr/bin/env python3

import os
import sys
import yaml
import subprocess


# chwall imports
from chwall.utils import BASE_CACHE_PATH, read_config, road_map_path
from chwall.wallpaper import build_wallpapers_list, choose_wallpaper, \
                             fetch_wallpaper, set_wallpaper


def blacklist_wallpaper():
    try:
        with open("{}/blacklist.yml"
                  .format(BASE_CACHE_PATH), "r") as f:
            blacklist = yaml.load(f) or []
    except FileNotFoundError:
        blacklist = []
    with open("{}/current_wallpaper"
              .format(BASE_CACHE_PATH), "r") as f:
        blacklist.append(f.readlines()[0].strip())
    with open("{}/blacklist.yml"
              .format(BASE_CACHE_PATH), "w") as f:
        yaml.dump(blacklist, f, explicit_start=True,
                  default_flow_style=False)


def display_wallpaper_info():
    with open("{}/current_wallpaper"
              .format(BASE_CACHE_PATH), "r") as f:
        infos = f.readlines()[1:]
    print("".join(infos))
    if len(sys.argv) > 2 and sys.argv[2] == "open" and \
       len(infos) == 2:
        url = infos[1].strip()
        if url != "":
            subprocess.run(["gio", "open", url])


def print_help():
    print("Usage: {} [ history | next | once | pending "
          "| systemd | info [ open ] ]"
          .format(sys.argv[0]), file=sys.stderr)


def run_client(config):
    # Is it an installed version?
    if os.path.exists("/usr/bin/chwall-daemon"):
        chwall_cmd = "/usr/bin/chwall-daemon"
    else:
        chwall_cmd = "{0}/chwall.py\nWorkingDirectory={0}".format(
            os.path.realpath(
                os.path.join(os.path.dirname(__file__), "..")))
    if sys.argv[1] == "systemd":
        print("""
[Unit]
Description = Simple wallpaper changer
After=network.target

[Service]
Type=forking
ExecStart={command}

[Install]
WantedBy=default.target
""".strip().format(command=chwall_cmd))
        sys.exit()
    if sys.argv[1] not in [
            "blacklist", "history", "info", "next", "pending", "quit"]:
        print_help()
        sys.exit(1)
    road_map = road_map_path()
    if not road_map:
        print("{} seems not to be running"
              .format(sys.argv[0]), file=sys.stderr)
        sys.exit(1)
    if sys.argv[1] == "info":
        display_wallpaper_info()
        sys.exit()
    action = sys.argv[1]
    if action == "blacklist":
        blacklist_wallpaper()
        action = "next"
    data = {}
    if action == "next":
        choose_wallpaper(road_map, config)
        sys.exit()
    with open(road_map, "r") as f:
        data = yaml.load(f)
    if action == "quit":
        print("Kill process {}".format(data["chwall_pid"]))
        # 15 == signal.SIGTERM
        os.kill(data["chwall_pid"], 15)
    elif action == "history":
        print("\n".join(data["history"]))
    elif action == "pending":
        print("\n".join(data["pictures"]))
    sys.exit()


def client():
    if len(sys.argv) == 1:
        print_help()
        sys.exit(1)

    config = read_config()

    if sys.argv[1] != "once":
        run_client(config)

    data = build_wallpapers_list(config)
    wp = fetch_wallpaper(data)
    set_wallpaper(wp[0], config)


if __name__ == "__main__":
    client()
