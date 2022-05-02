import os
import time
import yaml
import random
import shutil
import hashlib
import requests
import subprocess
from PIL import Image, ImageFilter
from importlib import import_module

# chwall imports
from chwall.utils import BASE_CACHE_PATH, get_screen_config, get_wall_config, \
                         get_logger, is_broken_picture

import gettext
# Uncomment the following line during development.
# Please, be cautious to NOT commit the following line uncommented.
# gettext.bindtextdomain("chwall", "./locale")
gettext.textdomain("chwall")
_ = gettext.gettext

logger = get_logger(__name__)


class ChwallWallpaperSetError(Exception):
    pass


WAIT_ERROR = 10


def build_wallpapers_list(config):
    logger.info(_("Fetching pictures addresses…"))
    collecs = {}
    for module_name in config["general"]["sources"]:
        try_again = 5
        ll = {}
        m = import_module("chwall.fetcher.{}".format(module_name))

        while try_again > 0:
            logger.info(
                _("Fetching pictures list from {name} - Attempt {number}")
                .format(name=module_name, number=(6 - try_again))
            )
            try:
                ll = m.fetch_pictures(config)
                try_again = 0
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.HTTPError,
                    requests.exceptions.Timeout) as e:
                logger.error(
                    _("Catch {error} exception while retrieving "
                      "images from {module}. Wait {time} seconds "
                      "before retrying.")
                    .format(
                        error=type(e).__name__, module=module_name,
                        time=WAIT_ERROR
                    )
                )

                try_again -= 1
                try:
                    time.sleep(WAIT_ERROR)
                except KeyboardInterrupt:
                    logger.warning(_("Retry NOW to connect to {module}")
                                   .format(module=module_name))
            except KeyboardInterrupt:
                logger.warning(_("Switch to next picture provider or exit"))
                try_again = 0
            except Exception as e:
                logger.error(
                    "{} in {}: {}".format(type(e).__name__, module_name, e)
                )
                break
        collecs.update(ll)
    return collecs


def filter_wallpapers_list(collecs):
    all_pics = list(collecs.keys())
    try:
        with open("{}/blacklist.yml"
                  .format(BASE_CACHE_PATH), "r") as f:
            blacklist = yaml.safe_load(f) or []
    except FileNotFoundError:
        blacklist = []
    all_pics_copy = all_pics.copy()
    for p in all_pics_copy:
        if p not in blacklist:
            continue
        logger.warning(
            _("Remove {picture} as it's in blacklist").format(picture=p)
        )
        all_pics.remove(p)
        collecs.pop(p)
    return (all_pics, collecs)


def build_roadmap(config):
    data = filter_wallpapers_list(build_wallpapers_list(config))
    all_pics = data[0]
    random.shuffle(all_pics)
    road_map = {"data": data[1], "pictures": all_pics, "history": []}
    with open("{}/roadmap".format(BASE_CACHE_PATH), "w") as f:
        yaml.dump(road_map, f, explicit_start=True, default_flow_style=False)


def set_xfce_wallpaper(path):
    if path is None:
        raise ChwallWallpaperSetError(_("No wallpaper path given"))
    wklist = subprocess.run(["xfconf-query", "-c", "xfce4-desktop",
                             "-l", "/backdrop"],
                            stdout=subprocess.PIPE)
    if wklist.returncode == 1:
        raise ChwallWallpaperSetError(
            _("Error while retrieving XFCE workspaces list")
        )
    for line in wklist.stdout.decode().strip().split("\n"):
        if not line.endswith("/last-image"):
            continue
        err = subprocess.run(["xfconf-query", "-c", "xfce4-desktop",
                              "-p", line, "--set", path])
        if err == 1:
            raise ChwallWallpaperSetError(
                _("Error while trying to set XFCE wallpaper in {prop}")
                .format(prop=line))
        zoom_line = line.replace("/last-image", "/image-style")
        subprocess.run(["xfconf-query", "-c", "xfce4-desktop",
                        "-p", zoom_line, "--set", "5"])


def prop_setting_error_str(desktop, prop):
    return _(
        "Error while setting {desktop} {prop} property"
    ).format(desktop=desktop, prop=prop)


def set_mate_wallpaper(path):
    if path is None:
        raise ChwallWallpaperSetError(_("No wallpaper path given"))
    err = subprocess.run(["gsettings", "set", "org.mate.background",
                          "picture-filename", path]).returncode
    if err == 1:
        raise ChwallWallpaperSetError(
            prop_setting_error_str("mate", "picture-filename"))
    err = subprocess.run(["gsettings", "set", "org.mate.background",
                          "picture-options", "zoom"]).returncode
    if err == 1:
        raise ChwallWallpaperSetError(
            prop_setting_error_str("mate", "picture-options"))


def set_gnome_wallpaper(path, where="background"):
    if path is None:
        raise ChwallWallpaperSetError(_("No wallpaper path given"))

    def _format_prop_error(prop):
        return prop_setting_error_str(
            "gnome", "{where} {prop}".format(where=where, prop=prop)
        )
    p = subprocess.run(
        ["gsettings", "list-keys", "org.gnome.desktop.{}".format(where)],
        capture_output=True, text=True)
    err2 = 0
    if "picture-uri-dark" in p.stdout:
        err2 = subprocess.run(
            ["gsettings", "set", "org.gnome.desktop.{}".format(where),
             "picture-uri-dark", "file://{}".format(path)]).returncode
    err = subprocess.run(
        ["gsettings", "set", "org.gnome.desktop.{}".format(where),
         "picture-uri", "file://{}".format(path)]).returncode
    
    if err == 1 or err2 == 1:
        raise ChwallWallpaperSetError(_format_prop_error("picture-uri"))
    err = subprocess.run(
        ["gsettings", "set", "org.gnome.desktop.{}".format(where),
         "picture-options", "zoom"]).returncode
    if err == 1:
        raise ChwallWallpaperSetError(_format_prop_error("picture-options"))


def set_nitrogen_wallpaper(path):
    if path is None:
        raise ChwallWallpaperSetError(_("No wallpaper path given"))
    cmd = ["nitrogen", "--set-zoom-fill", "--set-color=#000000", "--save"]
    # screen_info = (scr_number, scr_width, scr_height, scr_ratio, display)
    screen_info = get_screen_config()
    # wall_spec = (wall_width, wall_height, wall_ratio)
    wall_spec = get_wall_config(path)
    if wall_spec is None:
        wall_spec = (0, 0, 1)
    ratio_cmp = int(screen_info[3]) - int(wall_spec[2])
    if screen_info[0] > 1 and ratio_cmp != 0:
        err = 0
        for screen_index in range(screen_info[0]):
            head = "--head={}".format(screen_index)
            err += subprocess.run(cmd + [head, path]).returncode
        if err == 0:
            return
        raise ChwallWallpaperSetError(
            _("Error while calling nitrogen for multihead display"))
    err = subprocess.run(cmd + [path]).returncode
    if err != 0:
        raise ChwallWallpaperSetError(
            _("Error while calling nitrogen for single display"))


def set_mate_screensaver(path):
    if path is None:
        raise ChwallWallpaperSetError(_("No wallpaper path given"))
    err = subprocess.run(["gsettings", "set", "org.mate.screensaver",
                          "picture-filename", path]).returncode
    if err == 1:
        msg = _("screensaver {prop}".format(prop="picture-filename"))
        raise ChwallWallpaperSetError(prop_setting_error_str("mate", msg))


def set_gnome_screensaver(path):
    set_gnome_wallpaper(path, "screensaver")


def blur_picture(path, ld_path, radius):
    try:
        with Image.open(path) as im:
            # Save file format before possible conversion as format will be
            # lost by any picture operation.
            orig_format = im.format
            if im.mode != "RGB":
                logger.warning(
                    _("Converting non RGB picture {picture}")
                    .format(picture=path)
                )
                im = im.convert("RGB")
            im_blurred = im.filter(ImageFilter.GaussianBlur(radius))
            im_blurred.save(ld_path, orig_format)
    except ValueError as e:
        logger.error("{}: {}".format(path, e))
        # Copy original image if blurring fails.
        shutil.copy(path, ld_path)


def set_wallpaper(path, config):
    desktop = config["general"].get("desktop", "gnome")
    wall_method = "set_{}_wallpaper".format(desktop)
    if wall_method in globals():
        globals()[wall_method](path)
    else:
        set_gnome_wallpaper(path)
    shared_path = config["general"].get("shared", {}).get("path")
    screensaver_method = "set_{}_screensaver".format(desktop)
    if screensaver_method in globals():
        globals()[screensaver_method](shared_path or path)
    if shared_path is not None and shared_path != "":
        shared_path = os.path.expanduser(shared_path)
        if config["general"]["shared"].get("blur", False):
            radius = config["general"]["shared"].get("blur_radius", 20)
            blur_picture(path, shared_path, radius)
        else:
            shutil.copy(path, shared_path)
    return path


def fetch_wallpaper(wp_data):
    current_wall = clean_wallpaper_info(wp_data)
    pic_file = current_wall[4]

    def _write_current_wallpaper_info(current_wall):
        with open("{}/current_wallpaper".format(BASE_CACHE_PATH), "w") as f:
            for line in current_wall:
                f.write(line + "\n")

    if os.path.exists(pic_file):
        _write_current_wallpaper_info(current_wall)
        return pic_file, current_wall[0]

    try_again = 5
    while try_again > 0:
        try:
            pic_data = requests.get(current_wall[0]).content
            with open(pic_file, "wb") as f:
                f.write(pic_data)
            break
        except (requests.exceptions.ConnectionError,
                requests.exceptions.HTTPError,
                requests.exceptions.Timeout) as e:
            logger.error(
                _("Catch {error} exception while downloading {picture}. "
                  "Wait {time} seconds before retrying.")
                .format(error=type(e).__name__, picture=current_wall[0],
                        time=WAIT_ERROR)
            )
            try_again -= 1
            try:
                time.sleep(WAIT_ERROR)
            except KeyboardInterrupt:
                logger.warning(_("Retry NOW to download {picture}")
                               .format(picture=current_wall[0]))

    if not os.path.exists(pic_file):
        # We probably went here because of a network error. Thus do nothing yet
        # and move back without anything.
        return None, None
    if os.path.getsize(pic_file) == 0:
        # Do not keep empty files. It may be caused by a network error or
        # something else, which may be resolved later.
        os.unlink(pic_file)
        return None, None

    # Now check file with common placeholder, like broken image on reddit
    if is_broken_picture(pic_file):
        # Remove useless picture
        os.unlink(pic_file)
        # Blacklist it
        _write_current_wallpaper_info(current_wall)
        blacklist_wallpaper()
        # Pick next
        return "next", None

    _write_current_wallpaper_info(current_wall)
    return pic_file, current_wall[0]


def pick_wallpaper(config, backward=False, guard=False):
    road_map = "{}/roadmap".format(BASE_CACHE_PATH)
    if not os.path.exists(road_map):
        build_roadmap(config)
    with open(road_map, "r") as f:
        data = yaml.safe_load(f)
    no_pic_left = len(data.get("pictures", [])) == 0 and backward is False
    if no_pic_left or data is None:
        # Woops, no picture left. Removing current roadmap.
        os.unlink(road_map)
        if guard is True:
            # Wow, we already try to reload once, it's very bad to be
            # there. Maybe a little network error. Be patient
            logger.error(
                _("Impossible to build a new road map. It may be "
                  "caused by a temporarily network error. Please "
                  "try again later.")
            )
            return None
        # List is empty. Maybe it was the last picture of the current list?
        # Thus, try again now. Backward is always false because at this point,
        # something went wrong and we should start over.
        return pick_wallpaper(config, False, True)
    if backward is True:
        # Current wallpaper is the last of the history array. Thus we should go
        # back two times
        if len(data.get("history", [])) >= 2:
            # Current wall
            data["pictures"].insert(0, data["history"].pop())
            # Previous one
            data["pictures"].insert(0, data["history"].pop())
            # Now we are good to do a fake "forward" move
    lp, wp = fetch_wallpaper(data["data"][data["pictures"][0]])
    if lp is None:
        # Something goes wrong, thus do nothing. It may be because of a
        # networking error or something else.
        logger.error(
            _("Impossible to get any picture at this time. It may be "
              "caused by a temporarily network error. Please try again "
              "later.")
        )
        return None
    if lp == "next":
        # fetch_wallpaper already clean up thing, thus only return a new
        # pick_wallpaper call.
        return pick_wallpaper(config, backward)
    data["pictures"].remove(wp)
    data["history"].append(wp)
    with open(road_map, "w") as f:
        yaml.dump(data, f, explicit_start=True,
                  default_flow_style=False)
    try:
        lp = set_wallpaper(lp, config)
    except OSError as e:
        logger.error("{}: {}".format(type(e).__name__, e))
        remove_wallpaper_from_roadmap(wp)
        # Try again for next wallpaper
        return pick_wallpaper(config, backward)
    return lp


def remove_wallpaper_from_roadmap(wp):
    road_map = "{}/roadmap".format(BASE_CACHE_PATH)
    with open(road_map, "r") as f:
        data = yaml.safe_load(f)
    if wp in data.get("pictures", []):
        data["pictures"].remove(wp)
    if wp in data.get("history", []):
        data["history"].remove(wp)
    if wp in data.get("data", {}):
        wallinfo = clean_wallpaper_info(data["data"][wp])
        if wallinfo[3] != "local" and os.path.exists(wallinfo[4]):
            os.unlink(wallinfo[4])
        del data["data"][wp]
    with open(road_map, "w") as f:
        yaml.dump(data, f, explicit_start=True,
                  default_flow_style=False)


def blacklist_wallpaper():
    try:
        with open("{}/blacklist.yml"
                  .format(BASE_CACHE_PATH), "r") as f:
            blacklist = yaml.safe_load(f) or []
    except FileNotFoundError:
        blacklist = []
    with open("{}/current_wallpaper"
              .format(BASE_CACHE_PATH), "r") as f:
        blacklisted_pix = f.readlines()[0].strip()
    blacklist.append(blacklisted_pix)
    with open("{}/blacklist.yml"
              .format(BASE_CACHE_PATH), "w") as f:
        yaml.dump(blacklist, f, explicit_start=True,
                  default_flow_style=False)
    remove_wallpaper_from_roadmap(blacklisted_pix)


# This function may raise a PermissionError
def favorite_wallpaper_path(current_file, config):
    # Add file extension for better desktop integration
    with Image.open(current_file) as im:
        ext = (im.format or "").lower()
    if ext == "jpeg":
        ext = "jpg"
    ext = "." + ext
    filename = os.path.basename(current_file)
    if not filename.endswith(ext):
        filename += ext
    # Get favorite dir and create it if necessary
    fav_dir = config["general"]["favorites_path"]
    os.makedirs(fav_dir, exist_ok=True)
    return os.path.join(fav_dir, filename)


def favorite_wallpaper(config):
    with open("{}/current_wallpaper"
              .format(BASE_CACHE_PATH), "r") as f:
        curfile = f.readlines()[4].strip()
    try:
        target_file = favorite_wallpaper_path(curfile, config)
    except PermissionError as e:
        logger.error(e)
        return False
    if not os.path.exists(target_file):
        # Copy new favorite to its destination, only if it does not
        # exist in it yet.
        shutil.copy(curfile, target_file)
        return True
    return False


def clean_wallpaper_info(data):
    """Return the information array for a wallpaper

    The returned array is ready to be saved in current_wallpaper file.
    """
    if data["type"] == "local":
        pic_file = data["image"]
    else:
        m = hashlib.md5()
        m.update(data["image"].encode())
        pic_file = "{}/pictures/{}-{}".format(
            BASE_CACHE_PATH, data["type"], m.hexdigest())
    rights = data.get("copyright")
    if rights is None or rights == "":
        rights = _("{title} by {author}").format(
            title=data.get("description", _("Picture")),
            author=data.get("author", "unknown"))
    description = _("{title} (on {source})").format(
        title=rights.replace("\n", " "),
        source=data["type"])
    return [data["image"], description, data["url"],
            data["type"], pic_file]


def current_wallpaper_info():
    """Return a dictionnary containing the current wallpaper info.

    The returned dictionnary is built upon the content of the
    ``~/.cache/chwall/current_wallpaper`` file. This file is expected to
    respect the following format:

    :Example:

    line 0 contains wallpaper uri
    line 1 contains description
    line 2 contains remote page in case of remote wallpaper
    line 3 contains wallpaper type/origin
    line 4 contains wallpaper local path

    If the current wallpaper file is not found, or contains broken values, the
    following dictionnary is returned by default:

    :Example:

    wallinfo = {
        "remote-picture-uri": None,
        "description": None,
        "remote-uri": None,
        "type": None,
        "local-picture-path": None
    }

    That way, a complete dictionnary is **always** returned, and only its inner
    value may be ``None``.


    :return: current wallpaper information
    :rtype: dictionnary
    """
    curwall = []
    wallinfo = {
        "remote-picture-uri": None,
        "description": None,
        "remote-uri": None,
        "type": None,
        "local-picture-path": None
    }
    curfile = "{}/current_wallpaper".format(BASE_CACHE_PATH)
    if not os.path.isfile(curfile):
        return wallinfo
    with open(curfile, "r") as f:
        curwall = f.readlines()
    if len(curwall) != 5:
        return wallinfo
    local_file = curwall[4].strip()
    if not os.path.isfile(local_file):
        return wallinfo
    wallinfo["remote-picture-uri"] = curwall[0].strip()
    wallinfo["description"] = curwall[1].strip()
    wallinfo["remote-uri"] = curwall[2].strip()
    wallinfo["type"] = curwall[3].strip()
    wallinfo["local-picture-path"] = local_file
    return wallinfo
