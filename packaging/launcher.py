"""
Desktop launcher used by the installers (.dmg, .exe, .deb, .rpm, AppImage, Flatpak).

Starts the Unwind server on a free local port, opens it in your browser and shows a
small window with "Open in browser" and "Quit" so the app never runs invisibly.
`Unwind --mcp` runs the MCP server for coding agents instead.
"""
import os
import sys
import threading
import time
import urllib.request
import webbrowser

if getattr(sys, "frozen", False):
    # Installed apps can't write inside their own folder: keep notes in the home folder.
    os.environ.setdefault("UNWIND_VAULT", os.path.join(os.path.expanduser("~"), "Unwind Vault"))

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = getattr(sys, "_MEIPASS", os.path.dirname(HERE))
sys.path.insert(0, ROOT)


def run_mcp():
    import unwind_mcp
    unwind_mcp.main()


def main():
    if "--mcp" in sys.argv:
        return run_mcp()
    import app
    port = app.free_port(7878)
    url = f"http://127.0.0.1:{port}/"
    sys.argv = ["unwind", "--no-open", "--port", str(port)]
    threading.Thread(target=app.main, daemon=True).start()
    for _ in range(50):           # wait until the server answers, then open the browser
        try:
            import urllib.request
            urllib.request.urlopen(url, timeout=0.3)
            break
        except Exception:
            time.sleep(0.1)
    if os.environ.get("APP_SMOKE"):          # CI: prove the bundled app starts and serves its page, then exit
        try:
            ok = urllib.request.urlopen(url, timeout=10).status == 200
        except Exception as e:
            print("smoke test failed:", e, flush=True)
            ok = False
        print("smoke test:", "OK" if ok else "FAILED", url, flush=True)
        os._exit(0 if ok else 1)
    webbrowser.open(url)
    try:
        control_window(url)
    except Exception:
        print(f"Unwind is running at {url}  (close this window or press Ctrl+C to stop)", flush=True)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass


def control_window(url):
    import tkinter as tk
    root = tk.Tk()
    root.title("Unwind")
    root.resizable(False, False)
    bg, fg, accent = "#1c1d23", "#dfe0e6", "#8b7cf6"
    root.configure(bg=bg, padx=22, pady=18)
    try:
        icon = tk.PhotoImage(file=os.path.join(ROOT, "packaging", "icon.png")).subsample(16, 16)
        root.iconphoto(True, icon)
        tk.Label(root, image=icon, bg=bg).grid(row=0, column=0, rowspan=2, padx=(0, 14))
    except Exception:
        pass
    tk.Label(root, text="Unwind is running", font=("Helvetica", 15, "bold"), bg=bg, fg=fg).grid(row=0, column=1, sticky="w")
    tk.Label(root, text=url, font=("Menlo", 11), bg=bg, fg="#868996").grid(row=1, column=1, sticky="w")
    row = tk.Frame(root, bg=bg)
    row.grid(row=2, column=0, columnspan=2, pady=(14, 0), sticky="e")
    tk.Button(row, text="Open in browser", command=lambda: webbrowser.open(url), highlightbackground=bg,
              fg="#ffffff", bg=accent, relief="flat", padx=10).pack(side="left", padx=(0, 8))
    tk.Button(row, text="Quit", command=lambda: os._exit(0), highlightbackground=bg, relief="flat", padx=10).pack(side="left")
    root.protocol("WM_DELETE_WINDOW", lambda: os._exit(0))
    root.mainloop()
    os._exit(0)


if __name__ == "__main__":
    main()
