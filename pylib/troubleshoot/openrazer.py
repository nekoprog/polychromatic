#!/usr/bin/python3
#
# Polychromatic is licensed under the GPLv3.
# Copyright (C) 2020-2021 Luke Horwell <code@horwell.me>
#
"""
Troubleshooter for OpenRazer >2.0 and 3.x series.

Users occasionally may end up with installation problems due to the nature of
having a driver module and requirement of being in the 'plugdev' group.

Troubleshooting this aims to inform the user and prompt some guidelines to
get the system up and running again.

The future of OpenRazer aims to move to userspace, which will eliminate
a lot of the common driver issues.
"""

import glob
import requests
import os
import subprocess
import shutil

from .. import common

try:
    from openrazer import client as rclient
    PYTHON_LIB_PRESENT = True
except Exception:
    PYTHON_LIB_PRESENT = False


def _is_daemon_installed(_):
    return {
        "test_name": _("Daemon is installed"),
        "suggestions": [
            _("Install the 'openrazer-meta' package for your distribution.")
        ],
        "passed": True if shutil.which("openrazer-daemon") != None else False
    }


def _is_daemon_running(_):
    try:
        daemon_pid_file = os.path.join(os.environ["XDG_RUNTIME_DIR"], "openrazer-daemon.pid")
    except KeyError:
        daemon_pid_file = os.path.join("/run/user/", str(os.getuid()), "openrazer-daemon.pid")

    daemon_running = False
    if os.path.exists(daemon_pid_file):
        with open(daemon_pid_file) as f:
            daemon_pid = int(f.readline())
        if os.path.exists("/proc/" + str(daemon_pid)):
            daemon_running = True

    return {
        "test_name": _("Daemon is running"),
        "suggestions": [
            _("Start the daemon from the terminal. Run this command and look for errors:"),
            "$ openrazer-daemon -Fv",
        ],
        "passed": daemon_running
    }


def _is_pylib_installed(_):
    return {
        "test_name": _("Python library is installed"),
        "suggestions": [
            _("Install the 'python3-openrazer' package for your distribution."),
            _("Check the PYTHONPATH environment variable is correct."),
        ],
        "passed": PYTHON_LIB_PRESENT
    }


def _run_dkms_checks(_):
    dkms_installed_src = None
    dkms_installed_built = None
    uname = os.uname()
    subresults = []

    if PYTHON_LIB_PRESENT:
        dkms_version = rclient.__version__
        kernel_version = uname.release
        expected_dkms_src = "/var/lib/dkms/openrazer-driver/{0}".format(dkms_version)
        expected_dkms_build = "/var/lib/dkms/openrazer-driver/kernel-{0}-{1}".format(uname.release, uname.machine)

        # Is the OpenRazer DKMS module installed?
        dkms_installed_src = True if os.path.exists(expected_dkms_src) else False
        dkms_installed_built = True if os.path.exists(expected_dkms_build) else False

    subresults.append({
        "test_name": _("DKMS sources are installed"),
        "suggestions": [
            _("Install the 'openrazer-driver-dkms' package for your distribution."),
        ],
        "passed": dkms_installed_src
    })

    subresults.append({
        "test_name": _("DKMS module has been built for this kernel version"),
        "suggestions": [
            _("Ensure you have the correct Linux kernel headers package installed for your distribution."),
            _("Your distro's package system might not have rebuilt the DKMS module (this can happen with kernel or OpenRazer updates). Try running:"),
            "$ sudo dkms install -m openrazer-driver/x.x.x".replace("x.x.x", dkms_version),
        ],
        "passed": dkms_installed_built
    })

    # Can the DKMS module be loaded?
    modprobe = subprocess.Popen(["modprobe", "-n", "razerkbd"], stderr=subprocess.STDOUT, stdout=subprocess.PIPE)
    output = modprobe.communicate()[0].decode("utf-8")
    code = modprobe.returncode

    subresults.append({
        "test_name": _("DKMS module can be probed"),
        "suggestions": [
            _("For full error details, run:"),
            "$ sudo modprobe razerkbd",
        ],
        "passed": True if code == 0 else False
    })

    # Is a 'razer' DKMS module loaded right now?
    lsmod = subprocess.Popen(["lsmod"], stderr=subprocess.STDOUT, stdout=subprocess.PIPE)
    output = lsmod.communicate()[0].decode("utf-8")

    subresults.append({
        "test_name": _("DKMS module is currently loaded"),
        "suggestions": [
            _("For full error details, run:"),
            "$ sudo modprobe razerkbd"
        ],
        "passed": True if output.find("razer") != -1 else False
    })

    return subresults


def _is_secure_boot_enabled(_):
    sb_sysfile = glob.glob("/sys/firmware/efi/efivars/SecureBoot*")
    sb_reason = _("Secure Boot prevents the driver from loading, as OpenRazer's kernel modules built by DKMS are usually unsigned.")

    if len(sb_sysfile) > 0:
        # The last digit of this sysfs file indicates whether secure boot is enabled
        secureboot = subprocess.Popen(["od", "--address-radix=n", "--format=u1", sb_sysfile[0]], stdout=subprocess.PIPE)
        status = secureboot.communicate()[0].decode("utf-8").split(" ")[-1].strip()

        return {
            "test_name": _("Check Secure Boot (EFI) status"),
            "suggestions": [
                _("Secure boot is enabled. Turn it off in the system's EFI settings or sign the modules yourself."),
                sb_reason,
            ],
            "passed": True if int(status) == 0 else False
        }

    # Possibly "invalid argument". Can't be sure if it's on or off.
    return {
        "test_name": _("Check Secure Boot (EFI) status"),
        "suggestions": [
            _("Unable to automatically check. If it's enabled, turn it off in the system's EFI settings or sign the modules yourself."),
            sb_reason,
        ],
        "passed": None
    }


def _is_user_in_plugdev_group(_):
    groups = subprocess.Popen(["groups"], stdout=subprocess.PIPE).communicate()[0].decode("utf-8")
    return {
        "test_name": _("User account has been added to the 'plugdev' group"),
        "suggestions": [
            _("Run this command, log out, then log back in to the computer:"),
            "$ sudo gpasswd -a $USER plugdev",
            _("If you've recently installed, you may need to restart the computer."),
        ],
        "passed": True if groups.find("plugdev") != -1 else False
    }


def _is_sysfs_plugdev_permissions_ok(_):
    log_path = os.path.join(os.path.expanduser("~"), ".local/share/openrazer/logs/razer.log")

    if os.path.exists(log_path):
        with open(log_path) as f:
            log = f.readlines()

        return {
            "test_name": _("Check OpenRazer log for plugdev permission errors"),
            "suggestions": [
                _("Restarting (or replugging) usually fixes the problem."),
                _("To reset this error, clear the log:") + ' ' + log_path,
            ],
            "passed": True if "".join(log).find("Could not access /sys/") == -1 else False
        }


def _is_openrazer_up_to_date(_):
    if PYTHON_LIB_PRESENT:
        local_version = rclient.__version__
        remote_version = None
        remote_get_url = "https://openrazer.github.io/api/latest_version.txt"
        try:
            request = requests.get(remote_get_url)

            # Response should be 3 digits, e.g. 3.0.1
            if request.status_code == 200 and len(request.text.strip().split(".")) == 3:
                remote_version = request.text.strip()
        except Exception as e:
            # Gracefully ignore connection errors
            print("Could not retrieve OpenRazer data: {0}\n{1}".format(str(e), remote_get_url))
            request = None

        def _is_version_newer_then(verA, verB):
            verA = verA.split(".")
            verB = verB.split(".")
            is_new = False

            if int(verA[0]) > int(verB[0]):
                is_new = True

            if float(verA[1] + '.' + verA[2]) > float(verB[1] + '.' + verB[2]):
                is_new = True

            return is_new

        if remote_version:
            return {
                "test_name": _("OpenRazer is the latest version"),
                "suggestions": [
                    _("There is a new version of OpenRazer available."),
                    _("New versions add support for more devices and address device-specific issues."),
                    _("Your version: 0.0.0").replace("0.0.0", local_version),
                    _("Latest version: 0.0.0").replace("0.0.0", remote_version),
                ],
                "passed": _is_version_newer_then(remote_version, local_version) is not True
            }

        return {
            "test_name": _("OpenRazer is the latest version"),
            "suggestions": [
                _("Unable to retrieve this data from OpenRazer's website."),
                _("Check the OpenRazer website to confirm your device is listed as supported."),
                _("If you're checking the GitHub repository, check the 'stable' branch."),
            ],
            "passed": None
        }


def troubleshoot(_):
    """
    See: _backend.Backend.troubleshoot()
    """
    results = []

    # Abort if running on a non-Linux system. Troubleshooting was written for Linux.
    if os.uname().sysname != "Linux":
        return None

    try:
        # Perform the checks
        results.append(_is_daemon_installed(_))
        results.append(_is_pylib_installed(_))
        results.append(_is_daemon_running(_))
        results += _run_dkms_checks(_)

        # EFI systems only
        if os.path.exists("/sys/firmware/efi"):
            results.append(_is_secure_boot_enabled(_))

        results.append(_is_user_in_plugdev_group(_))
        results.append(_is_sysfs_plugdev_permissions_ok(_))
        results.append(_is_openrazer_up_to_date(_))

    except Exception as e:
        exception = common.get_exception_as_string(e)
        print("Failed to run OpenRazer troubleshooter!\n" + exception)
        return exception

    return results
