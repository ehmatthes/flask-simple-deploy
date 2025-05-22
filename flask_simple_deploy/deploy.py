"""Manage deployment to a variety of platforms.
"""

import sys, os, platform, re, subprocess, logging, shlex
from datetime import datetime
from pathlib import Path
from importlib import import_module
from importlib.metadata import version
import toml

from . import fsd_messages
from .utils import fsd_utils
from .utils import plugin_utils

from .utils.plugin_utils import fsd_config
from .utils.command_errors import DSDCommandError

from flask_simple_deploy.plugins import pm


class Deployer:

    def __init__(self, args):
        if args["automate_all"]:
            fsd_config.automate_all = True
        if args["local_testing"]:
            fsd_config.local_testing = True

    def deploy(self):
        # Do the deployment work.
        platform_module = self._load_plugin()
        pm.register(platform_module)
        self._validate_plugin(pm)

        platform_name = self.plugin_config.platform_name
        print(f"\nDeployment target: {platform_name}")

        self._inspect_system()
        self._inspect_project()

        self._confirm_automate_all(pm)

        # At this point fsd_config is fully defined, so we can validate it before handing
        # responsibility off to plugin.
        fsd_config.validate()

        # Platform-agnostic work is finished. Hand off to plugin.
        pm.hook.fsd_deploy()


    # --- Helper methods ---

    def _load_plugin(self):
        print("Loading plugin...")
        self.plugin_name = fsd_utils.get_plugin_name()
        print(f"  Using plugin: {self.plugin_name}")

        platform_module = import_module(f"{self.plugin_name}.deploy")
        return platform_module

    def _validate_plugin(self, pm):
        """Check that all required hooks are implemented by plugin.

        Also, load and validate plugin config object.

        Returns:
            None
        Raises:
            DSDCommandError: If plugin found invalid in any way.
        """
        plugin = pm.list_name_plugin()[0][1]

        callers = [caller.name for caller in pm.get_hookcallers(plugin)]

        required_hooks = [
            "fsd_get_plugin_config",
        ]
        for hook in required_hooks:
            if hook not in callers:
                msg = f"\nPlugin missing required hook implementation: {hook}()"
                raise DSDCommandError(msg)

        # Load plugin config, and validate config.
        self.plugin_config = pm.hook.fsd_get_plugin_config()[0]

        # Make sure there's a confirmation msg for automate_all if needed.
        if self.plugin_config.automate_all_supported and fsd_config.automate_all:
            if not hasattr(self.plugin_config, "confirm_automate_all_msg"):
                msg = "\nThis plugin supports --automate-all, but does not provide a confirmation message."
                raise DSDCommandError(msg)

    def _inspect_system(self):
        """Inspect the user's local system for relevant information.

        Uses fsd_config.on_windows and fsd_config.on_macos because those are clean checks to run.
        May want to refactor to fsd_config.user_system at some point. Don't ever use
        fsd_config.platform, because "platform" usually refers to the host we're deploying to.

        Linux is not mentioned because so far, if it works on macOS it works on Linux.
        """
        fsd_config.use_shell = False
        fsd_config.on_windows, fsd_config.on_macos = False, False
        if platform.system() == "Windows":
            fsd_config.on_windows = True
            fsd_config.use_shell = True
            print("Local platform identified: Windows")
        elif platform.system() == "Darwin":
            fsd_config.on_macos = True
            print("Local platform identified: macOS")

    def _inspect_project(self):
        """Inspect the local project.

        Find out everything we need to know about the project before making any remote
        calls.
            Determine project name.
            Find paths: .git/, settings, project root.
            Determine if it's a nested project or not.
            Get the dependency management approach: requirements.txt, Pipenv, Poetry
            Get current requirements.

        Anything that might cause us to exit before making the first remote call should
        be inspected here.

        Sets:
            self.local_project_name, self.project_root, self.settings_path,
            self.pkg_manager, self.requirements

        Returns:
            None
        """
        # Find .git location, and make sure there's a clean status.
        self._find_git_dir()
        self._check_git_status()

        # Set project root dir.
        fsd_config.project_root = Path.cwd()

        # Find out which package manager is being used: req_txt, poetry, or pipenv
        fsd_config.pkg_manager = "req_txt"
        msg = f"Dependency management system: {fsd_config.pkg_manager}"
        print(msg)

        fsd_config.requirements = self._get_current_requirements()

    def _find_git_dir(self):
        """Find .git/ location.
        """
        git_path = Path.cwd() / ".git"
        if git_path.exists():
            fsd_config.git_path = git_path
            print(f"Found .git dir at {fsd_config.git_path}.")
        else:
            error_msg = "Could not find a .git/ directory."
            error_msg += f"\n  Looked in {git_path.parent.as_posix()}."
            raise DSDCommandError(error_msg)

    def _check_git_status(self):
        """Make sure all non-dsd changes have already been committed.

        All configuration-specific work should be contained in a single commit. This
        allows users to easily revert back to the version of the project that worked
        locally, if the overall deployment effort fails, or if they don't like what
        django-simple-deploy does for any reason.

        Don't just look for a clean git status. Some uncommitted changes related to
        django-simple-deploy's work is acceptable, for example if they are doing a couple
        runs to get things right.

        Users can override this check with the --ignore-unclean-git flag.

        Returns:
            None: If status is such that `deploy` can continue.

        Raises:
            DSDCommandError: If any reason found not to continue.
        """

        cmd = "git status --porcelain"
        output_obj = plugin_utils.run_quick_command(cmd)
        status_output = output_obj.stdout.decode()

        cmd = "git diff --unified=0"
        output_obj = plugin_utils.run_quick_command(cmd)
        diff_output = output_obj.stdout.decode()

        proceed = fsd_utils.check_status_output(status_output, diff_output)

        if proceed:
            msg = "No uncommitted changes."
            print(msg)
        else:
            self._raise_unclean_error()

    def _raise_unclean_error(self):
        """Raise unclean git status error."""
        error_msg = fsd_messages.unclean_git_status
        if fsd_config.automate_all:
            error_msg += fsd_messages.unclean_git_automate_all

        raise DSDCommandError(error_msg)

    def _get_current_requirements(self):
        """Get current project requirements.

        We need to know which requirements are already specified, so we can add any that
        are needed on the remote platform. We don't need to deal with version numbers
        for most packages.

        Sets:
            self.req_txt_path

        Returns:
            List[str]: List of strings, each representing a requirement.
        """
        msg = "Checking current project requirements..."
        print(msg)

        if fsd_config.pkg_manager == "req_txt":
            fsd_config.req_txt_path = fsd_config.git_path.parent / "requirements.txt"
            requirements = fsd_utils.parse_req_txt(fsd_config.req_txt_path)

        # Report findings.
        msg = "  Found existing dependencies:"
        print(msg)
        for requirement in requirements:
            msg = f"    {requirement}"
            print(msg)

        return requirements

    def _confirm_automate_all(self, pm):
        """Confirm the user understands what --automate-all does.

        Also confirm that the selected plugin supports fully automated deployments.

        If confirmation not granted, exit with a message, but no error.
        """
        # Placing this check here keeps the handle() method cleaner.
        if not fsd_config.automate_all:
            return

        # Make sure this plugin supports automate-all.
        if not self.plugin_config.automate_all_supported:
            msg = "\nThis plugin does not support automated deployments."
            msg += "\nYou may want to try again without the --automate-all flag."
            raise DSDCommandError(msg)

        # Confirm the user wants to automate all steps.
        msg = self.plugin_config.confirm_automate_all_msg
        print(msg)
        confirmed = plugin_utils.get_confirmation()

        if confirmed:
            print("Automating all steps...")
        else:
            # Quit with a message, but don't raise an error.
            print(dsd_messages.cancel_automate_all)
            sys.exit()


def main(args):
    print("Configuring project for deployment...")

    deployer = Deployer(args)
    deployer.deploy()
