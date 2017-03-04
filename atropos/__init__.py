# coding: utf-8
import os
import sys

from atropos._version import get_versions
__version__ = get_versions()['version']
del get_versions

#__version__ = '1.0.16'

def check_importability():  # pragma: no cover
    try:
        import atropos._align
    except ImportError as e:
        if 'undefined symbol' in str(e):
            print("""
ERROR: A required extension module could not be imported because it is
incompatible with your system. A quick fix is to recompile the extension
modules with the following command:

    {0} setup.py build_ext -i

See the documentation for alternative ways of installing the program.

The original error message follows.
""".format(sys.executable))
        raise

def get_package_data(subdir, path):
    return os.path.join(
        os.path.abspath(os.path.dirname(__file__)), subdir, path)
