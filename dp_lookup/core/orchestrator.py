"""Backward-compatible import for the relocated application lookup service.

New code should import :func:`lookup_plot_pro` from
``dp_lookup.application.lookup_service``. This module remains intentionally
small so existing integrations using the historical path do not break.
"""

from dp_lookup.application.lookup_service import lookup_plot_pro

__all__ = ["lookup_plot_pro"]
