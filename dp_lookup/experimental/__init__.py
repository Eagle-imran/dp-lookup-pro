"""Opt-in experimental extensions.

Nothing in this package is part of the normal lookup path.  Experimental
commands are deliberately kept behind an explicit CLI namespace so they can
evolve without changing the stable lookup contract.
"""
"""Explicitly opt-in experimental capabilities.

Nothing in this package is part of the stable lookup, ingestion, or reporting
pipeline.  Experimental modules are deliberately isolated so they can evolve
without changing the authoritative lookup path.
"""
