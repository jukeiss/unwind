/* ForceGraph: a small canvas force-directed graph with pan/zoom/drag, hover focus, layered mode and flow particles. */
(function () {
  const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

  class ForceGraph {
    constructor(host, opts = {}) {
      this.host = host;
      this.o = Object.assign({
        directed: false, layered: false, layerGap: 220, particles: false, linkDistance: 80, charge: 260,
        gravity: 0.035, nodeRadius: () => 5, nodeColor: () => css("--muted"), nodeRing: () => null,
        nodeLabel: n => n.label || n.id, edgeWidth: () => 1, edgeColor: () => null, edgeDash: () => null,
        important: () => false, onSelect: () => {}, onOpen: () => {}, onHover: () => {}, labelZoom: 0.9,
      }, opts);
      this.canvas = document.createElement("canvas");
      host.appendChild(this.canvas);
      this.ctx = this.canvas.getContext("2d");
      this.nodes = []; this.edges = []; this.byId = new Map(); this.adj = new Map();
      this.k = 1; this.tx = 0; this.ty = 0; this.alpha = 0; this.hover = null; this.selected = null; this.dim = null;
      this.t = 0; this.raf = null; this.colors = {};
      this._readColors();
      this._bind();
      this.ro = new ResizeObserver(() => this._resize());
      this.ro.observe(host);
      this._resize();
      this.mq = matchMedia("(prefers-color-scheme: dark)");
      this._mq = () => { this._readColors(); this.draw(); };
      this.mq.addEventListener("change", this._mq);
      this._loop = this._loop.bind(this);
      this.raf = requestAnimationFrame(this._loop);
    }
    _readColors() {
      this.colors = { fg: css("--fg"), fg2: css("--fg-2"), muted: css("--muted"), faint: css("--faint"), line: css("--line-2"),
        accent: css("--accent"), bg: css("--bg"), in: css("--in"), out: css("--out") };
    }
    setOptions(o) { Object.assign(this.o, o); this.reheat(0.4); }
    setData({ nodes, edges }, keep = true) {
      const old = this.byId;
      const w = this.W || 800, h = this.H || 600;
      this.nodes = nodes.map(n => {
        const p = keep && old.get(n.id);
        const nn = Object.assign({}, n);
        if (p) { nn.x = p.x; nn.y = p.y; nn.vx = p.vx; nn.vy = p.vy; }
        else {
          const a = Math.random() * Math.PI * 2, r = 40 + Math.random() * 120;
          nn.x = this.o.layered ? (n.layer || 0) * this.o.layerGap + (Math.random() - .5) * 30 : Math.cos(a) * r;
          nn.y = Math.sin(a) * r; nn.vx = 0; nn.vy = 0;
        }
        return nn;
      });
      this.byId = new Map(this.nodes.map(n => [n.id, n]));
      this.edges = edges.filter(e => this.byId.has(e.source) && this.byId.has(e.target)).map(e => Object.assign({}, e, { s: this.byId.get(e.source), t: this.byId.get(e.target) }));
      const pair = new Set(this.edges.map(e => e.source + ">" + e.target));
      this.edges.forEach(e => { e.bi = pair.has(e.target + ">" + e.source); });
      this.adj = new Map(this.nodes.map(n => [n.id, new Set()]));
      this.edges.forEach(e => { this.adj.get(e.source).add(e.target); this.adj.get(e.target).add(e.source); });
      this.nodes.forEach(n => { n.deg = this.adj.get(n.id).size; });
      if (!keep || !old.size) { this.k = 1; this.tx = w / 2; this.ty = h / 2; this.userMoved = false; }
      this.reheat(1);
      if (!keep || !old.size) { this._fits = 0; this._needFit = true; setTimeout(() => this.fit(), 300); }
    }
    reheat(a = 0.6) { this.alpha = Math.max(this.alpha, a); }
    _resize() {
      const r = this.host.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
      const first = !this.W;
      this.W = r.width; this.H = r.height;
      this.canvas.width = Math.max(1, r.width * dpr); this.canvas.height = Math.max(1, r.height * dpr);
      this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (first) { this.tx = r.width / 2; this.ty = r.height / 2; }
      else if (!this.userMoved && this.nodes.length) { clearTimeout(this._rf); this._rf = setTimeout(() => this.fit(), 60); }
      this.draw();
    }
    toWorld(x, y) { return [(x - this.tx) / this.k, (y - this.ty) / this.k]; }
    nodeAt(x, y) {
      const [wx, wy] = this.toWorld(x, y);
      let best = null, bd = Infinity;
      for (const n of this.nodes) {
        const r = this.o.nodeRadius(n) + 4 / this.k, d = (n.x - wx) ** 2 + (n.y - wy) ** 2;
        if (d < r * r && d < bd) { bd = d; best = n; }
      }
      return best;
    }
    _bind() {
      const c = this.canvas; let drag = null, pan = null, moved = 0, last = 0;
      const pos = e => { const r = c.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
      c.addEventListener("pointerdown", e => {
        c.setPointerCapture(e.pointerId); const [x, y] = pos(e); moved = 0;
        const n = this.nodeAt(x, y);
        if (n) { drag = n; n.fx = n.x; n.fy = n.y; this.reheat(0.3); this.userMoved = true; }
        else pan = [x, y, this.tx, this.ty];
      });
      c.addEventListener("pointermove", e => {
        const [x, y] = pos(e);
        if (drag) { const [wx, wy] = this.toWorld(x, y); drag.fx = wx; drag.fy = wy; moved++; this.reheat(0.25); return; }
        if (pan) { this.tx = pan[2] + x - pan[0]; this.ty = pan[3] + y - pan[1]; moved++; if (moved > 2) this.userMoved = true; this.draw(); return; }
        const n = this.nodeAt(x, y);
        if (n !== this.hover) { this.hover = n; c.style.cursor = n ? "pointer" : "grab"; this.draw(); }
        this.o.onHover(n, e);
      });
      const up = e => {
        const [x, y] = pos(e);
        if (drag) {
          if (!e.shiftKey) { drag.fx = null; drag.fy = null; }
          if (moved < 3) {
            const now = Date.now();
            if (now - last < 320) this.o.onOpen(drag); else { this.selected = drag.id; this.o.onSelect(drag); }
            last = now;
          }
        } else if (pan && moved < 3) { this.selected = null; this.o.onSelect(null); }
        drag = null; pan = null; this.draw();
      };
      c.addEventListener("pointerup", up);
      c.addEventListener("pointerleave", () => { if (this.hover) { this.hover = null; this.o.onHover(null); this.draw(); } });
      c.addEventListener("wheel", e => {
        e.preventDefault();
        const [x, y] = pos(e), f = Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0018)); this.userMoved = true;
        this.zoomAt(x, y, f);
      }, { passive: false });
    }
    zoomAt(x, y, f) {
      const k2 = Math.min(6, Math.max(0.08, this.k * f));
      this.tx = x - (x - this.tx) * (k2 / this.k); this.ty = y - (y - this.ty) * (k2 / this.k); this.k = k2; this.draw();
    }
    zoomBy(f) { this.zoomAt(this.W / 2, this.H / 2, f); }
    fit(pad = 60) {
      if (!this.nodes.length) return;
      let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
      for (const n of this.nodes) { x0 = Math.min(x0, n.x); y0 = Math.min(y0, n.y); x1 = Math.max(x1, n.x); y1 = Math.max(y1, n.y); }
      const w = Math.max(60, x1 - x0), h = Math.max(60, y1 - y0);
      const bottom = 44;   // room for the legend
      this.k = Math.min(2.2, Math.max(0.1, Math.min((this.W - pad * 2) / w, (this.H - pad * 2 - bottom) / h)));
      this.tx = this.W / 2 - (x0 + w / 2) * this.k; this.ty = (this.H - bottom) / 2 - (y0 + h / 2) * this.k; this.draw();
    }
    focus(id) {
      const n = this.byId.get(id); if (!n) return;
      this.selected = id; this.tx = this.W / 2 - n.x * this.k; this.ty = this.H / 2 - n.y * this.k; this.draw();
    }
    setDim(fn) { this.dim = fn; this.draw(); }
    _tick() {
      const N = this.nodes, a = this.alpha, o = this.o;
      if (a < 0.004) return false;
      const ch = o.charge;
      for (let i = 0; i < N.length; i++) {
        const p = N[i];
        for (let j = i + 1; j < N.length; j++) {
          const q = N[j]; let dx = q.x - p.x, dy = q.y - p.y; let d2 = dx * dx + dy * dy;
          if (d2 > 250000) continue;
          if (d2 < 1) { dx = Math.random() - .5; dy = Math.random() - .5; d2 = 1; }
          const f = ch * a / d2, fx = dx * f, fy = dy * f;
          p.vx -= fx; p.vy -= fy; q.vx += fx; q.vy += fy;
        }
      }
      for (const e of this.edges) {
        const s = e.s, t = e.t; const dx = t.x - s.x, dy = t.y - s.y; const d = Math.sqrt(dx * dx + dy * dy) || 1;
        const L = o.layered ? o.linkDistance * 1.2 : o.linkDistance; const f = (d - L) / d * 0.06 * a;
        const bias = 1 / Math.max(1, Math.min(s.deg, t.deg) * 0.5);
        s.vx += dx * f * bias; s.vy += dy * f * bias; t.vx -= dx * f * bias; t.vy -= dy * f * bias;
      }
      for (const n of N) {
        if (o.layered) { n.vx += ((n.layer || 0) * o.layerGap - n.x) * 0.12 * a; n.vy += -n.y * o.gravity * 0.5 * a; }
        else { n.vx += -n.x * o.gravity * a; n.vy += -n.y * o.gravity * a; }
        if (n.fx != null) { n.x = n.fx; n.y = n.fy; n.vx = n.vy = 0; continue; }
        n.vx *= 0.6; n.vy *= 0.6; n.x += n.vx; n.y += n.vy;
      }
      this.alpha *= 0.985;
      return true;
    }
    _loop() {
      const moving = this._tick();
      if (this._needFit && !this.userMoved && (this.alpha < 0.12 || this._fits > 0) && this.t % 20 === 0) { this.fit(); this._fits++; if (this.alpha < 0.03) this._needFit = false; }
      this.t += 1;
      if (moving || (this.o.particles && !reduce)) this.draw();
      this.raf = requestAnimationFrame(this._loop);
    }
    draw() {
      const c = this.ctx, o = this.o, col = this.colors; if (!this.W) return;
      c.clearRect(0, 0, this.W, this.H);
      c.save(); c.translate(this.tx, this.ty); c.scale(this.k, this.k);
      const focus = this.hover || (this.selected && this.byId.get(this.selected));
      const nb = focus ? this.adj.get(focus.id) : null;
      const isLit = n => !focus || n === focus || (nb && nb.has(n.id));
      const dimmed = n => (this.dim && this.dim(n)) || !isLit(n);
      // edges
      for (const e of this.edges) {
        const lit = !focus || e.s === focus || e.t === focus;
        const w = Math.max(0.6, o.edgeWidth(e)) / Math.sqrt(this.k);
        c.globalAlpha = lit ? (focus ? 0.95 : 0.55) : 0.07;
        if (this.dim && (this.dim(e.s) || this.dim(e.t))) c.globalAlpha *= 0.25;
        c.strokeStyle = o.edgeColor(e) || col.line; c.lineWidth = w;
        const dash = o.edgeDash(e); c.setLineDash(dash ? dash.map(x => x / this.k) : []);
        const [mx, my] = this._ctrl(e);
        c.beginPath(); c.moveTo(e.s.x, e.s.y);
        if (e.bi) c.quadraticCurveTo(mx, my, e.t.x, e.t.y); else c.lineTo(e.t.x, e.t.y);
        c.stroke(); c.setLineDash([]);
        if (o.directed) this._arrow(e, w, mx, my);
        if (o.particles && lit && !reduce) this._particles(e, w);
      }
      c.globalAlpha = 1;
      // nodes
      for (const n of this.nodes) {
        const r = o.nodeRadius(n); const d = dimmed(n);
        c.globalAlpha = d ? 0.16 : 1;
        if (n.root) { c.fillStyle = o.nodeColor(n); c.globalAlpha *= 0.18; c.beginPath(); c.arc(n.x, n.y, r + 9, 0, 7); c.fill(); c.globalAlpha = d ? 0.16 : 1; }
        c.fillStyle = o.nodeColor(n); c.beginPath(); c.arc(n.x, n.y, r, 0, 7); c.fill();
        const ring = o.nodeRing(n);
        if (ring) { c.strokeStyle = ring; c.lineWidth = 2.2 / Math.sqrt(this.k); c.beginPath(); c.arc(n.x, n.y, r + 3 / Math.sqrt(this.k) + 1, 0, 7); c.stroke(); }
        if (this.selected === n.id) { c.strokeStyle = col.fg; c.lineWidth = 1.6 / this.k; c.beginPath(); c.arc(n.x, n.y, r + 6 / this.k + 2, 0, 7); c.stroke(); }
      }
      // labels
      c.textAlign = "center"; c.textBaseline = "top";
      const fs = 11.5 / this.k;
      c.font = `500 ${fs}px Inter, system-ui, sans-serif`;
      for (const n of this.nodes) {
        const show = n === focus || (nb && nb.has(n.id)) || this.selected === n.id || o.important(n) || this.k > o.labelZoom;
        if (!show) continue;
        const d = dimmed(n); c.globalAlpha = d ? 0.15 : (n === focus || this.selected === n.id ? 1 : 0.85);
        const label = o.nodeLabel(n); if (!label) continue;
        const y = n.y + o.nodeRadius(n) + 4 / this.k;
        c.lineWidth = 3 / this.k; c.strokeStyle = col.bg; c.strokeText(label, n.x, y);
        c.fillStyle = n === focus || this.selected === n.id ? col.fg : col.fg2; c.fillText(label, n.x, y);
      }
      c.restore(); c.globalAlpha = 1;
    }
    _ctrl(e) {
      const mx = (e.s.x + e.t.x) / 2, my = (e.s.y + e.t.y) / 2;
      if (!e.bi) return [mx, my];
      const dx = e.t.x - e.s.x, dy = e.t.y - e.s.y, d = Math.sqrt(dx * dx + dy * dy) || 1, off = Math.min(40, d * 0.18);
      return [mx - dy / d * off, my + dx / d * off];
    }
    _arrow(e, w, mx, my) {
      const c = this.ctx, r = this.o.nodeRadius(e.t) + 3 / this.k;
      const ax = e.bi ? mx : e.s.x, ay = e.bi ? my : e.s.y;
      const dx = e.t.x - ax, dy = e.t.y - ay, d = Math.sqrt(dx * dx + dy * dy) || 1;
      const ux = dx / d, uy = dy / d, tipx = e.t.x - ux * r, tipy = e.t.y - uy * r, s = Math.max(5, w * 3.2) / Math.sqrt(this.k) * 1.1;
      c.fillStyle = c.strokeStyle; c.beginPath(); c.moveTo(tipx, tipy);
      c.lineTo(tipx - ux * s - uy * s * 0.55, tipy - uy * s + ux * s * 0.55);
      c.lineTo(tipx - ux * s + uy * s * 0.55, tipy - uy * s - ux * s * 0.55); c.closePath(); c.fill();
    }
    _particles(e, w) {
      const c = this.ctx, n = Math.min(4, 1 + Math.floor(w));
      const [mx, my] = this._ctrl(e);
      c.fillStyle = this.o.edgeColor(e) || this.colors.accent;
      for (let i = 0; i < n; i++) {
        const t = ((this.t * 0.006 + i / n + (e.phase || (e.phase = Math.random()))) % 1);
        let x, y;
        if (e.bi) { const u = 1 - t; x = u * u * e.s.x + 2 * u * t * mx + t * t * e.t.x; y = u * u * e.s.y + 2 * u * t * my + t * t * e.t.y; }
        else { x = e.s.x + (e.t.x - e.s.x) * t; y = e.s.y + (e.t.y - e.s.y) * t; }
        c.globalAlpha = 0.9; c.beginPath(); c.arc(x, y, Math.max(1.4, w * 0.7) / Math.sqrt(this.k) * 1.2, 0, 7); c.fill();
      }
    }
    destroy() { cancelAnimationFrame(this.raf); this.ro.disconnect(); this.mq.removeEventListener("change", this._mq); this.canvas.remove(); }
  }
  window.ForceGraph = ForceGraph;
})();
