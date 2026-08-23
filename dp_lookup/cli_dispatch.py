"""Dispatch for non-lookup CLI namespaces.

The stable ``dp_lookup.cli`` facade owns the historical single-plot command.
Administrative and opt-in feature commands are kept behind this small lazy
router so importing the normal lookup path does not compose their services or
their optional dependencies.
"""

from __future__ import annotations

from typing import Optional, Sequence


def dispatch_admin_command(raw_args: Sequence[str]) -> Optional[int]:
    """Dispatch a recognized namespace, returning ``None`` for a lookup.

    Imports remain inside branches deliberately: a normal lookup should not
    import database lifecycle, authority, intelligence or experimental
    service implementations merely because they have CLI entry points.
    """
    if not raw_args:
        return None
    command = raw_args[0]
    if command == "experimental":
        from dp_lookup.experimental.assemblies_cli import main as experimental_main

        return int(experimental_main(raw_args))
    if command == "intelligence":
        from dp_lookup.intelligence_cli import main as intelligence_main

        return int(intelligence_main(raw_args))
    if command == "sources":
        from dp_lookup.authority_cli import main as authority_main

        return int(authority_main(raw_args))
    if command != "database":
        return None

    from dp_lookup.planning_snapshot_cli import COMMANDS as planning_commands

    if len(raw_args) > 1 and raw_args[1] in planning_commands:
        from dp_lookup.application.planning_database_services import LocalPlanningDatabaseServices
        from dp_lookup.planning_snapshot_cli import main as planning_database_main

        return int(planning_database_main(raw_args[1:], services=LocalPlanningDatabaseServices()))
    from dp_lookup.application.database_services import LocalDatabaseServices
    from dp_lookup.database_cli import main as database_main

    return int(database_main(raw_args, services=LocalDatabaseServices()))


__all__ = ["dispatch_admin_command"]

