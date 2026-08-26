#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys

import sys
import uuid
from types import ModuleType

# Bypass blocked C-extension by mocking uuid_utils using standard library uuid
mock_uuid_utils = ModuleType("uuid_utils")
mock_compat = ModuleType("uuid_utils.compat")

# Standard library uuid4 and uuid7 fallback (or mock uuid7 if on Python < 3.13)
def uuid7():
    return uuid.uuid4()  # Standard UUID fallback for LangChain compatibility

mock_uuid_utils.UUID = uuid.UUID
mock_uuid_utils.uuid7 = uuid7
mock_compat.uuid7 = uuid7
mock_uuid_utils.compat = mock_compat

sys.modules["uuid_utils"] = mock_uuid_utils
sys.modules["uuid_utils.compat"] = mock_compat


def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
