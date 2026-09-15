"""Explore workspace (STUB — replaced by the B builder): corpus_page(ctx), signal_page(ctx, channel_id)."""
from __future__ import annotations

import panel as pn

from .shell import header_pane


def corpus_page(ctx):
    return pn.Column(header_pane("Explore", "Corpus", "bird's-eye across every channel"),
                     pn.pane.HTML('<div class="pb-page"><div class="card card-pad">Explore › Corpus — to be built</div></div>'),
                     sizing_mode="stretch_width", margin=0)


def signal_page(ctx, channel_id: int):
    return pn.Column(header_pane("Explore", "Signal", f"channel {channel_id}"),
                     pn.pane.HTML('<div class="pb-page"><div class="card card-pad">Explore › Signal — to be built</div></div>'),
                     sizing_mode="stretch_width", margin=0)
