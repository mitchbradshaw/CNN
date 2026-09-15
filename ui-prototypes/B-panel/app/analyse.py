"""Analyse workspace (STUB — replaced by the B builder): chain_page(ctx), block_page(ctx, index)."""
from __future__ import annotations

import panel as pn

from .shell import header_pane


def chain_page(ctx):
    return pn.Column(header_pane("Analyse", "Chain", "build here · open a block to tune it"),
                     pn.pane.HTML('<div class="pb-page"><div class="card card-pad">Analyse › Chain — to be built</div></div>'),
                     sizing_mode="stretch_width", margin=0)


def block_page(ctx, index: int):
    return pn.Column(header_pane("Analyse", f"Block {index + 1:02d}", "process detail"),
                     pn.pane.HTML('<div class="pb-page"><div class="card card-pad">Analyse › Block — to be built</div></div>'),
                     sizing_mode="stretch_width", margin=0)
