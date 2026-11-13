/* Small Obsidian-flavoured Markdown renderer: frontmatter, [[wikilinks]], callouts, #tags, tasks, tables. */
(function () {
  const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const CALLOUT = {
    note: "var(--info)", info: "var(--info)", abstract: "var(--accent)", summary: "var(--accent)", tip: "var(--good)",
    success: "var(--good)", question: "var(--warn)", warning: "var(--warn)", caution: "var(--warn)", danger: "var(--danger)",
    error: "var(--danger)", bug: "var(--danger)", example: "var(--accent)", quote: "var(--muted)", todo: "var(--info)",
  };

  function parseFrontmatter(text) {
    if (!text.startsWith("---\n")) return [{}, text];
    const end = text.indexOf("\n---", 4);
    if (end < 0) return [{}, text];
    const block = text.slice(4, end), body = text.slice(end + 4).replace(/^\n+/, "");
    const fm = {}; let key = null;
    for (const line of block.split("\n")) {
      if (!line.trim()) continue;
      const m = line.match(/^([A-Za-z0-9_\-]+):\s*(.*)$/);
      if (m) {
        key = m[1]; let v = m[2].trim();
        if (v === "") fm[key] = [];
        else if (v.startsWith("[") && v.endsWith("]")) fm[key] = v.slice(1, -1).split(",").map(x => unq(x.trim())).filter(Boolean);
        else fm[key] = unq(v);
      } else if (key && /^\s*-\s+/.test(line)) {
        if (!Array.isArray(fm[key])) fm[key] = [];
        fm[key].push(unq(line.replace(/^\s*-\s+/, "")));
      }
    }
    return [fm, body];
  }
  function unq(v) { v = v.trim(); if (v.length > 1 && v[0] === v[v.length - 1] && `"'`.includes(v[0])) { try { return JSON.parse(v[0] === '"' ? v : `"${v.slice(1, -1)}"`); } catch { return v.slice(1, -1); } } return v; }

  function inline(s, ctx) {
    // protect code spans
    const codes = [];
    s = s.replace(/`([^`]+)`/g, (_, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000`; });
    s = esc(s);
    s = s.replace(/\[\[([^\]|#]+)(#[^\]|]*)?(?:\|([^\]]+))?\]\]/g, (_, t, h, a) => {
      const target = t.trim(); const ok = ctx.resolve ? ctx.resolve(target) : true;
      return `<a class="internal${ok ? "" : " unresolved"}" data-link="${esc(target)}" title="${esc(target)}">${a ? a : target}</a>`;
    });
    s = s.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, (_, alt, src) => /^https?:/.test(src) ? `<img alt="${alt}" src="${src}">` : alt);
    s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, t, u) => /^(https?:|mailto:)/.test(u) ? `<a href="${u}" target="_blank" rel="noopener noreferrer">${t}</a>` : t);
    s = s.replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, (_, p, u) => `${p}<a href="${u}" target="_blank" rel="noopener noreferrer">${u}</a>`);
    s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>").replace(/__([^_]+)__/g, "<strong>$1</strong>");
    s = s.replace(/(^|[^*\w])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>").replace(/(^|[^_\w])_([^_\s][^_]*)_(?!\w)/g, "$1<em>$2</em>");
    s = s.replace(/~~([^~]+)~~/g, "<del>$1</del>").replace(/==([^=]+)==/g, "<mark>$1</mark>");
    s = s.replace(/(^|\s)#([A-Za-z][\w/\-]*)/g, (_, p, t) => `${p}<a class="tag" data-tag="${t}">#${t}</a>`);
    s = s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${esc(codes[+i])}</code>`);
    return s;
  }

  function render(text, ctx = {}) {
    const lines = text.replace(/\r/g, "").replace(/<!--[\s\S]*?-->/g, "").split("\n");
    let i = 0; const out = [];
    function para(buf) { if (buf.length) out.push(`<p>${inline(buf.join(" "), ctx)}</p>`); }
    while (i < lines.length) {
      let line = lines[i];
      if (/^```/.test(line)) {
        const lang = line.slice(3).trim(); const buf = []; i++;
        while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
        i++;
        out.push(`<pre><code data-lang="${esc(lang)}">${esc(buf.join("\n"))}</code></pre>`); continue;
      }
      if (/^\s*$/.test(line)) { i++; continue; }
      let m;
      if ((m = line.match(/^(#{1,6})\s+(.*)$/))) { out.push(`<h${m[1].length}>${inline(m[2], ctx)}</h${m[1].length}>`); i++; continue; }
      if (/^(\*\*\*|---|___)\s*$/.test(line)) { out.push("<hr>"); i++; continue; }
      if (/^>/.test(line)) {
        const buf = [];
        while (i < lines.length && /^>/.test(lines[i])) buf.push(lines[i++].replace(/^>\s?/, ""));
        const cm = buf[0] && buf[0].match(/^\[!(\w+)\][+-]?\s*(.*)$/);
        if (cm) {
          const type = cm[1].toLowerCase(), color = CALLOUT[type] || "var(--info)";
          const title = cm[2] || type[0].toUpperCase() + type.slice(1);
          out.push(`<div class="callout-md" style="--c:${color}"><div class="ct">${inline(title, ctx)}</div><div class="cb">${render(buf.slice(1).join("\n"), ctx)}</div></div>`);
        } else out.push(`<blockquote>${render(buf.join("\n"), ctx)}</blockquote>`);
        continue;
      }
      if (/^\|.*\|\s*$/.test(line) && i + 1 < lines.length && /^\|?\s*:?-{2,}/.test(lines[i + 1])) {
        const row = l => l.trim().replace(/^\|/, "").replace(/(?<!\\)\|$/, "").split(/(?<!\\)\|/).map(c => c.trim().replace(/\\\|/g, "|"));
        const head = row(line), aligns = row(lines[i + 1]).map(c => c.endsWith(":") ? (c.startsWith(":") ? "center" : "right") : "left");
        i += 2; const rows = [];
        while (i < lines.length && /^\|.*\|\s*$/.test(lines[i])) rows.push(row(lines[i++]));
        const th = head.map((h, k) => `<th style="text-align:${aligns[k] || "left"}">${inline(h, ctx)}</th>`).join("");
        const tb = rows.map(r => `<tr>${r.map((c, k) => `<td style="text-align:${aligns[k] || "left"}">${inline(c, ctx)}</td>`).join("")}</tr>`).join("");
        out.push(`<table><thead><tr>${th}</tr></thead><tbody>${tb}</tbody></table>`); continue;
      }
      if (/^\s*([-*+]|\d+[.)])\s+/.test(line)) { const [html, n] = list(lines, i, ctx); out.push(html); i = n; continue; }
      const buf = [];
      while (i < lines.length && !/^\s*$/.test(lines[i]) && !/^(#{1,6}\s|```|>|\s*([-*+]|\d+[.)])\s+|\|.*\|\s*$)/.test(lines[i])) buf.push(lines[i++].trim());
      if (!buf.length) { buf.push(lines[i++]); }
      para(buf);
    }
    return out.join("\n");
  }

  function list(lines, i, ctx) {
    const indent = l => l.match(/^\s*/)[0].replace(/\t/g, "  ").length;
    const base = indent(lines[i]);
    const ordered = /^\s*\d+[.)]/.test(lines[i]);
    const items = [];
    while (i < lines.length) {
      const l = lines[i];
      if (/^\s*$/.test(l)) { if (i + 1 < lines.length && indent(lines[i + 1]) >= base && /^\s*([-*+]|\d+[.)])\s+/.test(lines[i + 1])) { i++; continue; } break; }
      const ind = indent(l);
      if (ind < base) break;
      if (ind > base) {
        if (/^\s*([-*+]|\d+[.)])\s+/.test(l) && items.length) { const [h, n] = list(lines, i, ctx); items[items.length - 1].sub += h; i = n; continue; }
        if (items.length) { items[items.length - 1].text += " " + l.trim(); i++; continue; }
      }
      const m = l.match(/^\s*(?:[-*+]|\d+[.)])\s+(.*)$/);
      if (!m) break;
      items.push({ text: m[1], sub: "" }); i++;
    }
    const lis = items.map(it => {
      const t = it.text.match(/^\[([ xX])\]\s+(.*)$/);
      if (t) return `<li class="task"><input type="checkbox" disabled ${t[1] !== " " ? "checked" : ""}>${inline(t[2], ctx)}${it.sub}</li>`;
      return `<li>${inline(it.text, ctx)}${it.sub}</li>`;
    }).join("");
    return [ordered ? `<ol>${lis}</ol>` : `<ul>${lis}</ul>`, i];
  }

  window.MD = { render, parseFrontmatter, esc, inline };
})();
