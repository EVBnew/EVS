"""
Compatibility layer.

All authentication & access logic lives in access_backend.py.
This file exists to keep existing imports working.
"""

from .access_backend import *  # noqa
