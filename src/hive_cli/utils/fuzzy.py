"""Re-export shim: fuzzy picker moved to ui/pickers/fuzzy.py.

NOTE (A0 step 6/7 overlap): kept here because fuzzy_select's callers
(utils/agents.py, utils/workdir.py, utils/editors.py, utils/profiles.py,
commands/wt.py, commands/status.py) carry pre-existing complexipy violations
(wt.py, status.py) or are otherwise deferred to later steps, so none of them
need touching this step. Imports the module (not individual functions)
per tests/test_architecture.py's
test_cross_layer_imports_are_modules_not_functions.
"""

from __future__ import annotations

from ..ui.pickers import fuzzy

FuzzyItem = fuzzy.FuzzyItem
fuzzy_select = fuzzy.fuzzy_select

__all__ = ["FuzzyItem", "fuzzy_select"]
