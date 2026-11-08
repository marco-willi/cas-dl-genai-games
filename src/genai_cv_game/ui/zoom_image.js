// Zoomable image (Streamlit Custom Component v2, inline).
//
//  * Hover (mouse): the image zooms in place and follows the pointer.
//  * Click / tap / Enter: full-screen viewer (wheel / pinch zoom, drag to pan,
//    double-click to reset, +/-/0/Esc keys). Images of one `group` (a real/AI
//    pair) open side by side; with `sync` their zoom and pan are linked.
//  * The small `src` loads immediately; the large `zoomSrc` loads on first
//    hover/open and replaces it seamlessly.
//
// Data (from Python): {id, src, zoomSrc, w, h, alt, label, group, pos, sync, zoom}

// ── Pure view math (unit-tested via QuickJS in tests/test_zoom_math.py) ──────
// A view is {z, cx, cy}: zoom relative to "fit" (1 = whole image visible) and
// the image point (0..1 coordinates) shown at the pane centre.

const MAX_ZOOM = 16;

/** Size of an nw×nh image scaled to fit a W×H pane (aspect preserved). */
function fitSize(W, H, nw, nh) {
  const f = Math.min(W / nw, H / nh);
  return { iw: nw * f, ih: nh * f };
}

/** Keep the view inside the image. */
function clampView(v, W, H, iw, ih) {
  const fx = Math.min(1, W / (iw * v.z)); // visible fraction of the image
  const fy = Math.min(1, H / (ih * v.z));
  const clampC = (c, f) => (f >= 1 ? 0.5 : Math.min(1 - f / 2, Math.max(f / 2, c)));
  return { z: v.z, cx: clampC(v.cx, fx), cy: clampC(v.cy, fy) };
}

/** Zoom by `factor`, keeping the image point under (px, py) fixed.
 *  px, py: pointer offset from the pane centre, in pixels. */
function zoomAround(v, factor, px, py, W, H, iw, ih) {
  const z2 = Math.min(MAX_ZOOM, Math.max(1, v.z * factor));
  const ux = v.cx + px / (iw * v.z);
  const uy = v.cy + py / (ih * v.z);
  return clampView(
    { z: z2, cx: ux - px / (iw * z2), cy: uy - py / (ih * z2) },
    W, H, iw, ih,
  );
}

/** Pan by a screen delta (dx, dy pixels); the content follows the pointer. */
function panBy(v, dx, dy, W, H, iw, ih) {
  return clampView(
    { z: v.z, cx: v.cx - dx / (iw * v.z), cy: v.cy - dy / (ih * v.z) },
    W, H, iw, ih,
  );
}

/** CSS transform for an iw×ih image element with transform-origin 0 0. */
function viewTransform(v, W, H, iw, ih) {
  const tx = W / 2 - v.cx * iw * v.z;
  const ty = H / 2 - v.cy * ih * v.z;
  return `translate(${tx}px, ${ty}px) scale(${v.z})`;
}

// ── Registry: components of one group find each other here ───────────────────

const REG = (window.__genaiZoom ??= { groups: new Map(), lightbox: null });
const STATE = new WeakMap();

function groupOf(id) {
  if (!REG.groups.has(id)) REG.groups.set(id, new Map());
  return REG.groups.get(id);
}

const clamp01 = (x) => Math.min(1, Math.max(0, x));

// ── Inline component ─────────────────────────────────────────────────────────

export default function (component) {
  const { data, parentElement } = component;
  const wrap = parentElement.querySelector(".wrap");
  const img = parentElement.querySelector(".img");
  if (!wrap || !img || !data) return undefined;

  // Runs again on every Streamlit rerun: keep this idempotent.
  const st = STATE.get(wrap) ?? STATE.set(wrap, { zoomReady: false, loading: false }).get(wrap);
  const level = data.zoom || 3;
  wrap.style.aspectRatio = `${data.w} / ${data.h}`;
  wrap.setAttribute("aria-label", `${data.alt || "Image"} — open zoom view`);
  img.alt = data.alt || "";
  if (!st.zoomReady && img.getAttribute("src") !== data.src) img.src = data.src;

  function preload() {
    if (st.zoomReady || st.loading || !data.zoomSrc) return;
    st.loading = true;
    const pre = new Image();
    pre.onload = () => {
      st.zoomReady = true;
      img.src = data.zoomSrc;
    };
    pre.onerror = () => {
      st.loading = false;
    };
    pre.src = data.zoomSrc;
  }

  function hoverAt(u, v) {
    img.style.transformOrigin = `${(u * 100).toFixed(2)}% ${(v * 100).toFixed(2)}%`;
    img.style.transform = `scale(${level})`;
    wrap.classList.add("zoomed");
  }

  function hoverEnd() {
    img.style.transform = "";
    wrap.classList.remove("zoomed");
  }

  const group = groupOf(data.group);
  const item = {
    id: data.id, pos: data.pos || 0, sync: !!data.sync,
    src: data.src, zoomSrc: data.zoomSrc, w: data.w, h: data.h,
    alt: data.alt, label: data.label,
    hoverAt, hoverEnd, preload,
  };
  group.set(data.id, item);
  const linked = () =>
    item.sync ? [...group.values()].filter((o) => o !== item && o.sync) : [];

  wrap.onpointerenter = (e) => {
    if (e.pointerType === "touch") return;
    preload();
    linked().forEach((o) => o.preload());
  };
  wrap.onpointermove = (e) => {
    if (e.pointerType === "touch") return;
    const r = wrap.getBoundingClientRect();
    const u = clamp01((e.clientX - r.left) / r.width);
    const v = clamp01((e.clientY - r.top) / r.height);
    hoverAt(u, v);
    linked().forEach((o) => o.hoverAt(u, v));
  };
  wrap.onpointerleave = () => {
    hoverEnd();
    linked().forEach((o) => o.hoverEnd());
  };
  wrap.onclick = () => openLightbox(data.group);
  wrap.onkeydown = (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openLightbox(data.group);
    }
  };

  return () => {
    const g = REG.groups.get(data.group);
    g?.delete(data.id);
    if (g && g.size === 0) REG.groups.delete(data.group);
  };
}

// ── Full-screen viewer ───────────────────────────────────────────────────────

const LB_CSS = `
:host { all: initial; }
.ov { position: fixed; inset: 0; display: flex; flex-direction: column;
  background: rgba(10, 10, 12, 0.94); color: #eee;
  font: 14px system-ui, -apple-system, "Segoe UI", sans-serif; outline: none; }
.panes { flex: 1; display: flex; gap: 8px; padding: 12px 12px 4px; min-height: 0; }
.pane { position: relative; flex: 1; min-width: 0; overflow: hidden;
  border-radius: 8px; background: #000; cursor: grab; touch-action: none;
  user-select: none; }
.pane.grab { cursor: grabbing; }
.pane img { position: absolute; left: 0; top: 0; max-width: none;
  transform-origin: 0 0; will-change: transform; user-select: none;
  -webkit-user-drag: none; }
.tag { position: absolute; top: 8px; left: 8px; z-index: 1; padding: 2px 8px;
  border-radius: 6px; background: rgba(0, 0, 0, 0.6); font-size: 12px;
  pointer-events: none; }
.bar { display: flex; gap: 6px; align-items: center; justify-content: center; padding: 8px; }
.bar button { min-width: 40px; height: 36px; padding: 0 10px; border: 1px solid #555;
  background: #222; color: #eee; border-radius: 8px; font-size: 16px; cursor: pointer; }
.bar button:hover { background: #333; }
.bar button:focus-visible { outline: 2px solid #8ab4ff; }
.lvl { min-width: 48px; text-align: center; font-variant-numeric: tabular-nums; }
.help { text-align: center; font-size: 12px; opacity: 0.65; padding: 0 12px 10px; }
@media (max-width: 700px) { .panes { flex-direction: column; } }
`;

function closeLightbox() {
  REG.lightbox?.close();
}

function openLightbox(groupId) {
  closeLightbox();
  const items = [...(REG.groups.get(groupId)?.values() ?? [])].sort((a, b) => a.pos - b.pos);
  if (!items.length) return;
  items.forEach((i) => i.hoverEnd());
  const linked = items.length > 1 && items.every((i) => i.sync);
  const opener = document.activeElement;

  const host = document.createElement("div");
  host.style.cssText = "position:fixed;inset:0;z-index:2147483000";
  const root = host.attachShadow({ mode: "open" });
  root.innerHTML = `<style>${LB_CSS}</style>
    <div class="ov" tabindex="-1" role="dialog" aria-modal="true" aria-label="Zoom view">
      <div class="panes"></div>
      <div class="bar" role="toolbar" aria-label="Zoom controls">
        <button data-a="out" aria-label="Zoom out">−</button>
        <span class="lvl" aria-live="polite">1.0×</span>
        <button data-a="in" aria-label="Zoom in">+</button>
        <button data-a="fit">Fit</button>
        <button data-a="close" aria-label="Close">✕</button>
      </div>
      <div class="help">Scroll or pinch to zoom · drag to pan · double-click to reset · Esc to close</div>
    </div>`;
  document.body.appendChild(host);
  const ov = root.querySelector(".ov");
  const panesEl = root.querySelector(".panes");
  const lvl = root.querySelector(".lvl");

  const views = items.map(() => ({ z: 1, cx: 0.5, cy: 0.5 }));
  const panes = items.map((it) => {
    const pane = document.createElement("div");
    pane.className = "pane";
    const im = document.createElement("img");
    im.src = it.src;
    im.alt = it.alt || "";
    im.draggable = false;
    pane.appendChild(im);
    if (it.label) {
      const tag = document.createElement("span");
      tag.className = "tag";
      tag.textContent = it.label;
      pane.appendChild(tag);
    }
    panesEl.appendChild(pane);
    if (it.zoomSrc) {
      const pre = new Image();
      pre.onload = () => {
        if (host.isConnected) im.src = it.zoomSrc;
      };
      pre.src = it.zoomSrc;
    }
    return { pane, im, it };
  });

  const dims = (p) => {
    const W = p.pane.clientWidth;
    const H = p.pane.clientHeight;
    return { W, H, ...fitSize(W, H, p.it.w, p.it.h) };
  };

  function render() {
    panes.forEach((p, i) => {
      const d = dims(p);
      p.im.style.width = `${d.iw}px`;
      p.im.style.height = `${d.ih}px`;
      views[i] = clampView(views[i], d.W, d.H, d.iw, d.ih);
      p.im.style.transform = viewTransform(views[i], d.W, d.H, d.iw, d.ih);
    });
    lvl.textContent = `${views[0].z.toFixed(1)}×`;
  }

  /** Apply make(dims, view) -> view to pane i (and to all panes when linked). */
  function update(i, make) {
    const next = make(dims(panes[i]), views[i]);
    if (linked) views.forEach((_, j) => (views[j] = { ...next }));
    else views[i] = next;
    render();
  }

  const reset = () => ({ z: 1, cx: 0.5, cy: 0.5 });

  panes.forEach((p, i) => {
    const pane = p.pane;
    const rel = (e, d) => {
      const r = pane.getBoundingClientRect();
      return [e.clientX - r.left - d.W / 2, e.clientY - r.top - d.H / 2];
    };

    pane.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        const unit = e.deltaMode === 1 ? 0.05 : 0.0015;
        const factor = Math.exp(-e.deltaY * unit * (e.ctrlKey ? 3 : 1));
        update(i, (d, v) => {
          const [px, py] = rel(e, d);
          return zoomAround(v, factor, px, py, d.W, d.H, d.iw, d.ih);
        });
      },
      { passive: false },
    );

    const pointers = new Map();
    let lastDist = 0;
    let lastMid = null;
    const two = () => [...pointers.values()].slice(0, 2);
    const distOf = () => {
      const [a, b] = two();
      return Math.hypot(a.x - b.x, a.y - b.y) || 1;
    };
    const midOf = () => {
      const [a, b] = two();
      return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
    };

    pane.onpointerdown = (e) => {
      pane.setPointerCapture(e.pointerId);
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      pane.classList.add("grab");
      if (pointers.size === 2) {
        lastDist = distOf();
        lastMid = midOf();
      }
    };
    pane.onpointermove = (e) => {
      const prev = pointers.get(e.pointerId);
      if (!prev) return;
      const cur = { x: e.clientX, y: e.clientY };
      pointers.set(e.pointerId, cur);
      if (pointers.size === 1) {
        update(i, (d, v) => panBy(v, cur.x - prev.x, cur.y - prev.y, d.W, d.H, d.iw, d.ih));
      } else if (pointers.size >= 2) {
        const nd = distOf();
        const nm = midOf();
        update(i, (d, v) => {
          const r = pane.getBoundingClientRect();
          const zoomed = zoomAround(
            v, nd / lastDist, nm.x - r.left - d.W / 2, nm.y - r.top - d.H / 2,
            d.W, d.H, d.iw, d.ih,
          );
          return panBy(zoomed, nm.x - lastMid.x, nm.y - lastMid.y, d.W, d.H, d.iw, d.ih);
        });
        lastDist = nd;
        lastMid = nm;
      }
    };
    const endPointer = (e) => {
      pointers.delete(e.pointerId);
      if (!pointers.size) pane.classList.remove("grab");
    };
    pane.onpointerup = endPointer;
    pane.onpointercancel = endPointer;

    pane.ondblclick = (e) =>
      update(i, (d, v) => {
        if (v.z > 1.01) return reset();
        const [px, py] = rel(e, d);
        return zoomAround(v, 3, px, py, d.W, d.H, d.iw, d.ih);
      });
  });

  function step(action) {
    panes.forEach((_, i) => {
      if (linked && i > 0) return;
      update(i, (d, v) =>
        action === "fit"
          ? reset()
          : zoomAround(v, action === "in" ? 1.5 : 1 / 1.5, 0, 0, d.W, d.H, d.iw, d.ih),
      );
    });
  }

  root.querySelector(".bar").onclick = (e) => {
    const action = e.target.closest("button")?.dataset.a;
    if (action === "close") close();
    else if (action) step(action);
  };
  ov.onclick = (e) => {
    if (e.target === ov || e.target === panesEl) close();
  };
  ov.addEventListener("wheel", (e) => e.preventDefault(), { passive: false });

  const onKey = (e) => {
    const k = e.key;
    if (k === "Escape") close();
    else if (k === "+" || k === "=") step("in");
    else if (k === "-" || k === "_") step("out");
    else if (k === "0") step("fit");
    else return;
    e.preventDefault();
    e.stopPropagation(); // keep Streamlit's own shortcuts out of it
  };
  window.addEventListener("keydown", onKey, true);
  const ro = new ResizeObserver(render);
  ro.observe(panesEl);

  function close() {
    window.removeEventListener("keydown", onKey, true);
    ro.disconnect();
    host.remove();
    if (REG.lightbox && REG.lightbox.host === host) REG.lightbox = null;
    if (opener && typeof opener.focus === "function") opener.focus();
  }

  REG.lightbox = { host, close };
  render();
  ov.focus();
}
