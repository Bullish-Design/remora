"""LSP-facing models.

Wire-protocol specific models for the Neovim LSP adapter.
RewriteProposal and generate_id now live in remora.runner.models.
"""

from remora.runner.models import RewriteProposal, generate_id

__all__ = ["RewriteProposal", "generate_id"]
