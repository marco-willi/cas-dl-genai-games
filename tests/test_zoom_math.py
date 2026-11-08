"""Tests for the zoom viewer's view math, run against the real JS file.

Needs a JS engine: `uv run --with quickjs pytest tests/test_zoom_math.py`
(skipped when the `quickjs` package is not installed). Loading the file also
proves that the whole component module parses.
"""

import json
from pathlib import Path

import pytest

quickjs = pytest.importorskip("quickjs")

JS_FILE = Path("src/genai_cv_game/ui/zoom_image.js")


@pytest.fixture(scope="module")
def ctx():
    source = JS_FILE.read_text().replace(
        "export default function (component)", "function __component(component)"
    )
    c = quickjs.Context()
    c.eval("var window = {};")  # the module registers a global on load
    c.eval(source)
    return c


def run(ctx, expr: str):
    return json.loads(ctx.eval(f"JSON.stringify({expr})"))


def test_fit_size_preserves_aspect(ctx):
    d = run(ctx, "fitSize(800, 400, 1000, 1000)")
    assert d == {"iw": 400, "ih": 400}
    d = run(ctx, "fitSize(800, 800, 2000, 1000)")
    assert d == {"iw": 800, "ih": 400}


def test_fit_view_is_centred(ctx):
    # z = 1: the whole image is visible, centred in the pane.
    t = run(ctx, "viewTransform({z:1,cx:0.5,cy:0.5}, 800, 400, 400, 400)")
    assert t == "translate(200px, 0px) scale(1)"


def test_zoom_keeps_point_under_pointer_fixed(ctx):
    # Image point under the pointer before and after zooming must be identical.
    js = """
    (() => {
      const W = 900, H = 600, iw = 900, ih = 600, bad = [];
      let seed = 7;
      const rnd = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
      for (let n = 0; n < 300; n++) {
        let v = clampView({z: 1 + rnd() * 6, cx: rnd(), cy: rnd()}, W, H, iw, ih);
        const px = (rnd() - 0.5) * W * 0.5, py = (rnd() - 0.5) * H * 0.5;
        const f = 0.5 + rnd() * 1.5;
        const before = [v.cx + px / (iw * v.z), v.cy + py / (ih * v.z)];
        const w = zoomAround(v, f, px, py, W, H, iw, ih);
        const after = [w.cx + px / (iw * w.z), w.cy + py / (ih * w.z)];
        if (w.z > 1 && w.z < 16 &&
            (Math.abs(before[0] - after[0]) > 1e-9 || Math.abs(before[1] - after[1]) > 1e-9)) {
          // only allowed when the clamp had to pull the view back inside the image
          const fx = Math.min(1, W / (iw * w.z)), fy = Math.min(1, H / (ih * w.z));
          const atEdge = Math.abs(w.cx - fx / 2) < 1e-9 || Math.abs(w.cx - (1 - fx / 2)) < 1e-9 ||
                         Math.abs(w.cy - fy / 2) < 1e-9 || Math.abs(w.cy - (1 - fy / 2)) < 1e-9 ||
                         fx >= 1 || fy >= 1;
          if (!atEdge) bad.push({v, px, py, f, w});
        }
      }
      return bad;
    })()
    """
    assert run(ctx, js) == []


def test_views_stay_inside_the_image(ctx):
    js = """
    (() => {
      const W = 700, H = 500, iw = 500, ih = 500, bad = [];
      let seed = 3;
      const rnd = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
      let v = {z: 1, cx: 0.5, cy: 0.5};
      for (let n = 0; n < 500; n++) {
        const r = rnd();
        if (r < 0.4) v = zoomAround(v, 0.6 + rnd() * 1.2, (rnd()-.5)*W, (rnd()-.5)*H, W, H, iw, ih);
        else v = panBy(v, (rnd()-.5)*400, (rnd()-.5)*400, W, H, iw, ih);
        const fx = Math.min(1, W / (iw * v.z)), fy = Math.min(1, H / (ih * v.z));
        const ok = v.z >= 1 && v.z <= MAX_ZOOM &&
          v.cx - fx / 2 >= -1e-9 && v.cx + fx / 2 <= 1 + 1e-9 &&
          v.cy - fy / 2 >= -1e-9 && v.cy + fy / 2 <= 1 + 1e-9;
        if (!ok) bad.push(v);
      }
      return bad;
    })()
    """
    assert run(ctx, js) == []


def test_zoom_is_capped_and_floored(ctx):
    v = run(ctx, "zoomAround({z:15,cx:.5,cy:.5}, 10, 0, 0, 800, 600, 800, 600)")
    assert v["z"] == 16
    v = run(ctx, "zoomAround({z:2,cx:.5,cy:.5}, 0.01, 0, 0, 800, 600, 800, 600)")
    assert v == {"z": 1, "cx": 0.5, "cy": 0.5}


def test_pan_moves_content_with_the_pointer(ctx):
    # Dragging right by 100 px moves the content right = the view centre left.
    v = run(ctx, "panBy({z:4,cx:.5,cy:.5}, 100, 0, 800, 600, 800, 600)")
    assert v["cx"] == pytest.approx(0.5 - 100 / (800 * 4))
    assert v["cy"] == 0.5


def test_pan_is_reversible_away_from_edges(ctx):
    v = run(
        ctx,
        "panBy(panBy({z:4,cx:.5,cy:.5}, 60, -40, 800, 600, 800, 600),"
        " -60, 40, 800, 600, 800, 600)",
    )
    assert v["cx"] == pytest.approx(0.5)
    assert v["cy"] == pytest.approx(0.5)
