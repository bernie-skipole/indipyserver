
import sys

from .ipyserver import IPyServer

if sys.version_info < (3, 11):
    raise ImportError('indipyserver requires Python >= 3.11')

version = "0.0.1"
