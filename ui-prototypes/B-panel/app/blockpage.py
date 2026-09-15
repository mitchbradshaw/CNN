"""Block page (frame chain-7b) — placeholder until built."""
import panel as pn


def block_page(ctx, index: int):
    return pn.Column(ctx.header("Analyse", f"Block {index + 1:02d}", "process detail"),
                     pn.pane.HTML('<div class="pb-page"><div class="card card-pad">Block page — to be built</div></div>'),
                     sizing_mode="stretch_width", margin=0)
