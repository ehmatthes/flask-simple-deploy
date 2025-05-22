"""Utilities for django-simple-deploy, to be used by platform-specific plugins.

Note: Some of these utilities are used by django-simple-deploy internally as well.
"""

import logging
import re
import subprocess
import shlex
import toml
from pathlib import Path

# from django.template.engine import Engine, Context
# from django.utils.safestring import mark_safe

from .. import fsd_messages
from .fsd_config import FSDConfig
from .command_errors import DSDCommandError


# Create dsd_config once right here. The attributes are set in deploy.py,
# and then accessible by plugins. This approach keeps from having to pass the config
# instance between core, plugins, and these utility functions.
fsd_config = FSDConfig()


def add_file(path, contents):
    """Add a new file to the project.

    This function is meant to be used when adding new files that don't typically
    exist in a Django project that runs locally. For example, a platform-specific
    Dockerfile. See the `add_dockerfile()` method in Fly.io's deployer module.

    If the file does not exist, it is written to the project. If the file already
    exists, the user is prompted for permission to overwrite the file.

    Returns:
    - None

    Raises:
    - DSDCommandError: If file exists, and user does not give permission
    to overwrite file.
    """

    print(f"\n  Looking in {path.parent} for {path.name}...")

    if path.exists():
        proceed = get_confirmation(fsd_messages.file_found(path.name))
        if not proceed:
            raise DSDCommandError(fsd_messages.file_replace_rejected(path.name))
    else:
        print(f"    File {path.name} not found. Generating file...")

    # File does not exist, or we are free to overwrite it.
    path.write_text(contents)

    msg = f"\n    Wrote {path.name} to {path}"
    print(msg)


# def modify_file(path, contents):
#     """Modify an existing file.

#     This function is meant for modifying a file that should already exist, such as
#     settings.py. We're not getting permission; if unwanted changes are somehow made,
#     the user can use Git to restore the file to its original state.

#     Returns:
#     - None

#     Raises:
#     - DSDCommandError: If file does not exist.
#     """
#     # Make sure file exists.
#     if not path.exists():
#         msg = f"File {path.as_posix()} does not exist."
#         raise DSDCommandError(msg)

#     # Rewrite file with new contents.
#     path.write_text(contents)
#     msg = f"  Modified file: {path.as_posix()}"
#     write_output(msg)


# def modify_settings_file(template_path, context=None):
#     """Add a platform-specific settings block to settings.py.

#     Provide a path to a template including current settings and the platform-specific
#     settings block, and a context dictionary.
#     """
#     if context is None:
#         context = {}
#     # Add current settings to context.
#     settings_string = dsd_config.settings_path.read_text()
#     safe_settings_string = mark_safe(settings_string)
#     context["current_settings"] = safe_settings_string

#     modified_settings_string = get_template_string(template_path, context)

#     # Write settings to file.
#     modify_file(dsd_config.settings_path, modified_settings_string)


# def add_dir(path):
#     """Write a new directory to the file.

#     This function is meant to be used when adding new directories that don't
#     typically exist in a Django project. For example, a platform-specific directory
#     such as .platform/ for Platform.sh.

#     Only adds the directory; does nothing if the directory already exists.

#     Returns:
#     - None
#     """
#     write_output(f"\n  Looking for {path.as_posix()}...")

#     if path.exists():
#         write_output(f"    Found {path.as_posix()}")
#     else:
#         path.mkdir()
#         write_output(f"    Added new directory: {path.as_posix()}")


# def get_numbered_choice(prompt, valid_choices, quit_message):
#     """Select from a numbered list of choices.

#     This is used, for example, to select from a number of apps that the user
#     has created on a platform.
#     """
#     prompt += "\n\nYou can quit by entering q.\n"

#     while True:
#         # Show prompt and get selection.
#         log_info(prompt)

#         selection = input(prompt)
#         log_info(selection)

#         if selection.lower() in ["q", "quit"]:
#             raise DSDCommandError(quit_message)

#         # Make sure they entered a number
#         try:
#             selection = int(selection)
#         except ValueError:
#             msg = "Please enter a number from the list of choices."
#             write_output(msg)
#             continue

#         # Validate selection.
#         if selection not in valid_choices:
#             msg = "  Invalid selection. Please try again."
#             write_output(msg)
#             continue

#         return selection


def run_quick_command(cmd, check=False, skip_logging=False):
    """Run a command that should finish quickly.

    Commands that should finish quickly can be run more simply than commands that
    will take a long time. For quick commands, we can capture output and then deal
    with it however we like, and the user won't notice that we first captured
    the output.

    The `check` parameter is included because some callers will need to handle
    exceptions. For example, see prep_automate_all() in deploy_platformsh.py. Most
    callers will only check stderr, or maybe the returncode; they won't need to
    involve exception handling.

    Returns:
        CompletedProcess

    Raises:
        CalledProcessError: If check=True is passed, will raise CalledProcessError
        instead of returning a CompletedProcess instance with an error code set.
    """
    if fsd_config.on_windows:
        output = subprocess.run(cmd, shell=True, capture_output=True)
    else:
        cmd_parts = shlex.split(cmd)
        output = subprocess.run(cmd_parts, capture_output=True, check=check)

    return output


def run_slow_command(cmd):
    """Run a command that may take some time.

    For commands that may take a while, we need to stream output to the user, rather
    than just capturing it. Otherwise, the command will appear to hang.
    """

    # DEV: This only captures stderr right now.
    # The first call I used this for was `git push heroku`. That call writes to
    # stderr; I believe streaming to stdout and stderr requires multithreading. The
    # current approach seems to be working for all calls that use it.
    #
    # Adding a parameter stdout=subprocess.PIPE and adding a separate identical loop
    # over p.stdout misses stderr. Maybe combine the loops with zip()? SO posts on
    # this topic date back to Python2/3 days.
    cmd_parts = cmd.split()
    with subprocess.Popen(
        cmd_parts,
        stderr=subprocess.PIPE,
        bufsize=1,
        universal_newlines=True,
        shell=fsd_config.use_shell,
    ) as p:
        for line in p.stderr:
            print(line)

    if p.returncode != 0:
        raise subprocess.CalledProcessError(p.returncode, p.args)


def get_confirmation(msg="Are you sure you want to do this?"):
    """Get confirmation for an action.

    Assumes an appropriate message has already been displayed about what is to be
    done. Shows a yes|no prompt. You can pass a different message for the prompt; it
    should be phrased to elicit a yes/no response.

    Returns:
        bool: True if confirmation granted, False if not granted.
    """
    prompt = f"\n{msg} (yes|no) "
    confirmed = ""

    while True:
        print(prompt)
        confirmed = input()

        if confirmed.lower() in ("y", "yes"):
            return True
        elif confirmed.lower() in ("n", "no"):
            return False
        else:
            print("  Please answer yes or no.")


# def check_settings(platform_name, start_line, msg_found, msg_cant_overwrite):
#     """Check if a platform-specific settings block already exists.

#     If so, ask if we can overwrite that block. This is much simpler than trying to
#     keep track of individual settings.

#     Returns:
#         None

#     Raises:
#         DSDCommandError: If we can't overwrite existing platform-specific
#         settings block.
#     """
#     settings_text = dsd_config.settings_path.read_text()

#     re_platform_settings = f"(.*)({start_line})(.*)"
#     m = re.match(re_platform_settings, settings_text, re.DOTALL)

#     if not m:
#         log_info(f"No {platform_name}-specific settings block found.")
#         return

#     # A platform-specific settings block exists. Get permission to overwrite it.
#     if not get_confirmation(msg_found):
#         raise DSDCommandError(msg_cant_overwrite)

#     # Platform-specific settings exist, but we can remove them and start fresh.
#     dsd_config.settings_path.write_text(m.group(1))

#     msg = f"  Removed existing {platform_name}-specific settings block."
#     write_output(msg)


def commit_changes():
    """Commit changes that have been made to the project.

    This should only be called when automate_all is being used.
    """
    if not fsd_config.automate_all:
        return

    print("  Committing changes...")

    cmd = "git add ."
    output = run_quick_command(cmd)
    print(output)

    cmd = 'git commit -m "Configured project for deployment."'
    output = run_quick_command(cmd)
    print(output)


def add_packages(package_list):
    """Add a set of packages to the project's requirements.

    This is a simple wrapper for add_package(), to make it easier to add multiple
    requirements at once. If you need to specify a version for a particular package,
    use add_package().

    Returns:
        None
    """
    for package in package_list:
        add_package(package)


def add_package(package_name, version=""):
    """Add a package to the project's requirements, if not already present.

    Handles calls with version information with pip formatting:
        add_package("psycopg2", version="<2.9")
    The utility helpers handle this version information correctly for the dependency
    management system in use.

    Returns:
        None
    """
    print(f"\nLooking for {package_name}...")

    if package_name in fsd_config.requirements:
        print(f"  Found {package_name} in requirements file.")
        return

    add_req_txt_pkg(fsd_config.req_txt_path, package_name, version)

    print(f"  Added {package_name} to requirements file.")


# def get_template_string(template_path, context):
#     """Given a template and context, return contents as a string.

#     Contents can then be written to a file.

#     Returns:
#     - Str: single string representing contents of the rendered template.
#     """
#     my_engine = Engine()
#     template = my_engine.from_string(template_path.read_text())
#     return template.render(Context(context))


# def get_user_info(prompt, strip_response=True):
#     """Ask the user for some information.

#     If you want to preserve whitespace, pass strip_response=False.

#     The main benefit to using this function is consistent logging.
#     Returns:
#     - Str: User's response, after calling strip().
#     """
#     log_info(prompt)
#     response = input(prompt)
#     log_info(response)

#     if strip_response:
#         return response.strip()
#     else:
#         return response


# # --- Helper functions ---


# def get_string_from_output(output):
#     """Convert output to string.

#     Output may be a string, or an instance of subprocess.CompletedProcess.

#     This function assumes that output is either stdout *or* stderr, but not both. If we
#     need to display both, consider redirecting stderr to stdout:
#         subprocess.run(cmd_parts, stderr=subprocess.STDOUT, ...)
#     This has not been necessary yet; if it becomes necessary we'll probably need to
#     modify run_quick_command() to accommodate the necessary args.
#     """
#     if isinstance(output, str):
#         return output

#     if isinstance(output, subprocess.CompletedProcess):
#         # Extract subprocess output as a string. Assume output is either stdout or
#         # stderr, but not both.
#         output_str = output.stdout.decode()
#         if not output_str:
#             output_str = output.stderr.decode()

#         return output_str


def add_req_txt_pkg(req_txt_path, package, version):
    """Add a package to requirements.txt."""
    contents = req_txt_path.read_text()
    pkg_string = f"\n{package + version}"
    req_txt_path.write_text(contents + pkg_string + "\n")
