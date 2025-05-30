# from django.core.management.base import CommandError


# class DSDCommandError(CommandError):
class DSDCommandError:
    """Simple wrapper around CommandError, to facilitate consistent
    logging of command errors.

    Writes "DSDCommandError:" and error message to log, then raises
    actual CommandError.

    Note: This changes the exception type from CommandError to
    DSDCommandError.
    """

    def __init__(self, message):
        raise RuntimeError(message)
        """Log the error, and then raise a standard CommandError."""

        # Importing plugin_utils or log_info at the module level causes a circular
        # import error, because plugin_utils imports DSDCommandError.
        # This seems like a reasonable place to avoid the circular import.
        # from .plugin_utils import log_info

        # log_info("\nDSDCommandError:")
        # log_info(message)
        # super().__init__(message)
