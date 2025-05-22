import pluggy

from . import hookspecs


pm = pluggy.PluginManager("flask_simple_deploy")
pm.add_hookspecs(hookspecs)
