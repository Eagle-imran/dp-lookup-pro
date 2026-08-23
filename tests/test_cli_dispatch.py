"""Contracts for lazy routing of non-lookup CLI namespaces."""

import dp_lookup.cli_dispatch as dispatch


def test_unrecognized_namespace_is_left_for_the_lookup_parser():
    assert dispatch.dispatch_admin_command(["WORLI", "733"]) is None


def test_empty_args_are_left_for_the_lookup_parser():
    assert dispatch.dispatch_admin_command([]) is None

