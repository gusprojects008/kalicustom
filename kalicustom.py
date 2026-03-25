# python 3.13

import sys
import os
import subprocess
import typing
import json
import shutil
import logging
import argparse
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
THEMES_DIR = SCRIPT_DIR / "themes"
PACKAGES_JSON = THEMES_DIR / "packages.json"
SUPPORTED_WALLPAPERS = ["kalitheme"]
KALITHEME_PACKAGES_TXT = THEMES_DIR / "kalitheme" / "kalitheme-packages.txt"
KALITHEME_WALLPAPERS_DIR = THEMES_DIR / "kalitheme" / "wallpapers"

DISTRO_MAP = {
    "arch": {
        "manager": "pacman",
        "cmds": {
            "install": ["pacman", "-S", "--noconfirm"],
            "remove": ["pacman", "-Rns", "--noconfirm"],
        }
    },
    "void": {
        "manager": "xbps-install",
        "cmds": {
            "install": ["xbps-install", "-Sy"],
            "remove": ["xbps-remove", "-Ry"],
        }
    },
    "debian": {
        "manager": "apt",
        "cmds": {
            "install": ["apt", "install", "-y"],
            "remove": ["apt", "remove", "-y"],
        }
    },
    "ubuntu": {
        "manager": "apt",
        "cmds": {
            "install": ["apt", "install", "-y"],
            "remove": ["apt", "remove", "-y"],
        }
    },
    "fedora": {
        "manager": "dnf",
        "cmds": {
            "install": ["dnf", "install", "-y"],
            "remove": ["dnf", "remove", "-y"],
        }
    }
}

class ColoredFormatter(logging.Formatter):
    GREY = "\x1b[38;20m"
    CYAN = "\x1b[36;20m"
    YELLOW = "\x1b[33;20m"
    RED = "\x1b[31;20m"
    BOLD_RED = "\x1b[31;1m"
    RESET = "\x1b[0m"

    FORMATS = {
        logging.DEBUG: GREY + "%(message)s" + RESET,
        logging.INFO: CYAN + "[*] %(message)s" + RESET,
        logging.WARNING: YELLOW + "[!] %(message)s" + RESET,
        logging.ERROR: RED + "[ERROR] %(message)s" + RESET,
        logging.CRITICAL: BOLD_RED + "[CRITICAL] %(message)s" + RESET,
    }

    def format(self, record: logging.LogRecord) -> str:
        log_fmt = self.FORMATS.get(record.levelno, "%(message)s")
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)

def setup_logging() -> None:
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(ColoredFormatter())
    logger.addHandler(handler)
    logger.propagate = False

def detect_package_manager():
    try:
        with open("/etc/os-release") as f:
            lines = f.readlines()
    except FileNotFoundError:
        logging.error("Could not read /etc/os-release.")
        sys.exit(1)

    data = {}
    for line in lines:
        line = line.strip()
        if not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            data[key.strip().lower()] = value.strip().strip('"').lower()

    primary_id = data.get("id")
    like_ids = data.get("id_like", "").split()

    info = None
    detected = None

    if primary_id and primary_id in DISTRO_MAP:
        info = DISTRO_MAP[primary_id]
        detected = primary_id
    else:
        for like in like_ids:
            if like in DISTRO_MAP:
                info = DISTRO_MAP[like]
                detected = like
                break

    if not info:
        logging.error("Unsupported or undetected Linux distribution.")
        sys.exit(1)

    manager = info["manager"]

    if not shutil.which(manager):
        logging.critical(f"Package manager '{manager}' not found in PATH.")
        sys.exit(1)

    logging.info(f"Detected distro '{detected}' with package manager '{manager}'")
    return info["cmds"]

def run_subprocess(command: list[str], sudo: bool = False, check: bool = True) -> subprocess.CompletedProcess:
    if sudo:
        command = ["sudo"] + command

    logging.info(f"Running command: {' '.join(command)}")

    try:
        return subprocess.run(command, check=check, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        logging.exception(f"Command failed: {' '.join(command)}")
        raise
    except FileNotFoundError:
        logging.error(f"Command not found: {command[0]}")
        sys.exit(1)

def read_utilities_list(utilities_list_path: Path) -> list[str]:
    logging.info(f"Reading utilities list from '{utilities_list_path}'")
    try:
        with open(utilities_list_path, "r", encoding="utf-8") as file:
            return [line.strip() for line in file if line.strip()]
    except FileNotFoundError:
        logging.error(f"Utilities file '{utilities_list_path}' not found.")
        sys.exit(1)

def install_utilities(utilities_list_path: Path):
    utilities = read_utilities_list(utilities_list_path)

    if not utilities:
        logging.warning("The utilities list is empty. No action will be taken.")
        return

    logging.info(f"Installing utilities... (Packages to install: {', '.join(utilities)})")
    
    try:
        run_subprocess(PACKAGE_MANAGER["install"] + utilities, True)
        logging.info(f"Utilities {', '.join(utilities)} were successfully installed.")
    except subprocess.CalledProcessError:
        logging.error("Failed to install the utilities.")
        sys.exit(1)

def uninstall_utilities(utilities_list_path: Path):
    utilities = read_utilities_list(utilities_list_path)

    if not utilities:
        logging.warning("The utilities list is empty. No action will be taken.")
        return

    logging.info(f"Uninstalling utilities... (Packages to uninstall: {', '.join(utilities)})")

    try:
        run_subprocess(PACKAGE_MANAGER["remove"] + utilities, True)
        logging.info(f"Utilities {', '.join(utilities)} were successfully uninstalled.")
    except subprocess.CalledProcessError:
        logging.error("Failed to uninstall the utilities.")
        sys.exit(1)

def expand_path(path: Path) -> Path:
    return Path(os.path.expanduser(os.path.expandvars(str(path)))).resolve()

def safe_copy(src: Path, dst: Path) -> None:
    src = expand_path(src)
    dst = expand_path(dst)

    dst.parent.mkdir(parents=True, exist_ok=True)

    try:
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True, symlinks=True)
        else:
            shutil.copy2(src, dst)
    except PermissionError:
        logging.info(f"Retrying with sudo: {src} -> {dst}")
        run_subprocess(["cp", "-a", str(src), str(dst)], True)
    except Exception as e:
        logging.exception(f"Copy failed: {src} -> {dst}")
        pass

def create_backup(path: Path) -> None:
    expanded_path = expand_path(path)

    if not expanded_path.exists():
        return

    counter = 1
    backup_path = expanded_path.with_suffix(expanded_path.suffix + ".old")

    while backup_path.exists():
        backup_path = expanded_path.with_suffix(
            expanded_path.suffix + f".old.{counter}"
        )
        counter += 1

    logging.info(f"Creating backup: {expanded_path} -> {backup_path}")
    safe_copy(expanded_path, backup_path)

def restore_from_backup(path: Path) -> None:
    expanded_path = expand_path(path)

    backups = list(expanded_path.parent.glob(expanded_path.name + ".old*"))
    if not backups:
        logging.warning(f"No backup found for: {expanded_path}")
        return

    backups.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    latest_backup = backups[0]

    logging.info(f"Restoring {latest_backup} -> {expanded_path}")
    safe_copy(latest_backup, expanded_path)

def config_apply(src: typing.Union[str, list], dst: typing.Union[str, list]):
    if isinstance(src, list) and isinstance(dst, list):
        if len(src) != len(dst):
            logging.error("Error: source and destination lists have different lengths.")
            return
        for s, d in zip(src, dst):
            safe_copy(THEMES_DIR / s, Path(d))
    else:
        safe_copy(THEMES_DIR / str(src), Path(str(dst)))

def load_json_packages(json_path: Path) -> dict:
    try:
        with open(json_path, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception as error:
        logging.critical(f"Failed to load {json_path}: {error}")
        sys.exit(1)

def install_kalitheme():
    logging.info("Installing Kalitheme...")
    json_data = load_json_packages(PACKAGES_JSON)
    system_packages = json_data.get("System packages", {}).get("kalitheme", {})
    packages_configs = json_data.get("Packages config", {}).get("kalitheme", {})

    utilities = list(system_packages.keys())

    if utilities:
        logging.info(f"Packages to be installed: {', '.join(utilities)}")
        KALITHEME_PACKAGES_TXT.write_text("\n".join(utilities), encoding="utf-8")
        install_utilities(KALITHEME_PACKAGES_TXT)

    logging.info("[STARTING BACKUP PROCESS]")
    for pkg_cfg in system_packages.values():
        paths = [pkg_cfg] if isinstance(pkg_cfg, str) else pkg_cfg
        for path in paths:
            if path.strip():
                create_backup(Path(path.strip()))

    logging.info("[APPLYING SETTINGS]")
    for pkg, src_config in packages_configs.items():
        dst_config = system_packages.get(pkg)
        if dst_config:
            logging.info(f"Applying settings for {pkg}: {src_config} -> {dst_config}")
            config_apply(src_config, dst_config)
    
    logging.info("Kalitheme installed successfully!")

def uninstall_kalitheme():
    logging.info("Uninstalling Kalitheme...")
    json_data = load_json_packages(PACKAGES_JSON)
    system_packages = json_data.get("System packages", {}).get("kalitheme", {})

    logging.info("[STARTING RESTORE PROCESS]")
    for pkg_cfg in system_packages.values():
        paths = [pkg_cfg] if isinstance(pkg_cfg, str) else pkg_cfg
        for path in paths:
            if path.strip():
                restore_from_backup(Path(path.strip()))

    CRITICAL_KEYWORDS = ("bash", "i3", "python")
    utilities = [pkg for pkg in system_packages if not any(keyword in pkg for keyword in CRITICAL_KEYWORDS)]
    
    if utilities:
        logging.info(f"Packages to be uninstalled: {', '.join(utilities)}")
        KALITHEME_PACKAGES_TXT.write_text("\n".join(utilities), encoding="utf-8")
        uninstall_utilities(KALITHEME_PACKAGES_TXT)
    else:
        logging.info("No packages to uninstall.")

    logging.info("Kalitheme uninstalled successfully!")

def dynamic_background(sec: int, mode: str, wallpapers_path_str: str, wallpapers_type: str):
    if wallpapers_type not in SUPPORTED_WALLPAPERS:
        logging.error(f"Wallpaper type not supported. Supported: {SUPPORTED_WALLPAPERS}")
        sys.exit(1)

    try:
        run_subprocess(PACKAGE_MANAGER["install"] + ["feh"], True)
    except subprocess.CalledProcessError:
        logging.exception("Could not install feh. Aborting.")
        sys.exit(1)
    
    wallpapers_path = expand_path(Path(wallpapers_path_str)) / wallpapers_type / "wallpapers"
    
    logging.info(f"Copying wallpapers from '{KALITHEME_WALLPAPERS_DIR}' to '{wallpapers_path}'")
    create_backup(wallpapers_path)
    safe_copy(KALITHEME_WALLPAPERS_DIR, wallpapers_path)

    try:
        run_subprocess(["pkill", "-f", ".dynamic_background.sh"], False, False)
    except PermissionError:
        run_subprocess(["pkill", "-f", ".dynamic_background.sh"], True, False)

    script_path = expand_path(Path("~/.dynamic_background.sh"))
    script_content = f"""#!/bin/bash
# Auto-generated by Kalicustom
while true; do
  mapfile -t W < <(find "{wallpapers_path}" -maxdepth 1 -type f)
  if [ ${{#W[@]}} -eq 0 ]; then
    sleep {sec}
    continue
  fi
"""
    if mode == "randomize":
        script_content += f'  feh --no-fehbg --bg-scale --randomize "${{W[@]}}"\n'
    elif mode == "ordered":
        script_content += f'  for img in "${{W[@]}}"; do\n    feh --no-fehbg --bg-scale "$img"\n    sleep {sec}\n  done\n'
    else:
        logging.error("Invalid mode! Use 'randomize' or 'ordered'.")
        sys.exit(1)
        
    script_content += f"  sleep {sec}\ndone &\n"
    
    script_path.write_text(script_content, encoding="utf-8")
    script_path.chmod(0o755)
    logging.info(f"Dynamic wallpaper script created at {script_path}")
    
    i3_config_path = expand_path(Path("~/.config/i3/config"))
    if i3_config_path.exists():
        answer = input(f"[*] Do you want to add '{script_path}' to i3 startup? (y/n): ").strip().lower()
        if answer == 'y':
            exec_line = f"exec --no-startup-id {script_path} # by Kalicustom\n"
            content = i3_config_path.read_text(encoding="utf-8")
            if exec_line not in content:
                with open(i3_config_path, "a", encoding="utf-8") as f:
                    f.write("\n" + exec_line)
                logging.info(f"Execution line added to {i3_config_path}")
    
    try:
        subprocess.Popen([str(script_path)])
        logging.info(f"Dynamic wallpaper started from {script_path}.")
    except Exception as e:
        logging.error(f"Error executing {script_path}: {e}")

def main():
    parser = argparse.ArgumentParser(
        description="Kalicustom: A tool to automate the installation and configuration of themes and utilities.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command", required=True, help="Available commands")

    p_install = subparsers.add_parser("install-utilities", help="Install utilities from a list.")
    p_install.add_argument("utilities_list", type=Path, help="Path to the .txt file with the list of utilities.")
    p_install.set_defaults(func=lambda args: install_utilities(args.utilities_list))

    p_uninstall = subparsers.add_parser("uninstall-utilities", help="Uninstall utilities from a list.")
    p_uninstall.add_argument("utilities_list", type=Path, help="Path to the .txt file with the list of utilities.")
    p_uninstall.set_defaults(func=lambda args: uninstall_utilities(args.utilities_list))

    p_install_theme = subparsers.add_parser("install-kalitheme", help="Apply the Kali theme.")
    p_install_theme.set_defaults(func=lambda args: install_kalitheme())
    
    p_uninstall_theme = subparsers.add_parser("uninstall-kalitheme", help="Remove the Kali theme and restore backups.")
    p_uninstall_theme.set_defaults(func=lambda args: uninstall_kalitheme())

    p_dynamic_bg = subparsers.add_parser("dynamic-background", help="Set up a dynamic wallpaper.")
    p_dynamic_bg.add_argument("sec", type=int, help="Seconds between wallpaper changes.")
    p_dynamic_bg.add_argument("mode", choices=["randomize", "ordered"], help="Switching mode (random or ordered).")
    p_dynamic_bg.add_argument("wallpapers_path", type=str, help="Directory to save the wallpapers.")
    p_dynamic_bg.add_argument("wallpapers_type", choices=SUPPORTED_WALLPAPERS, help="Type of wallpaper pack.")
    p_dynamic_bg.set_defaults(func=lambda args: dynamic_background(args.sec, args.mode, args.wallpapers_path, args.wallpapers_type))

    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    setup_logging()
    PACKAGE_MANAGER = detect_package_manager()
    try:
        main()
    except Exception as e:
        logging.critical(f"An unhandled error occurred: {e}", exc_info=True)
        sys.exit(1)
