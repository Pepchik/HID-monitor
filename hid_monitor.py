import locale
import queue
import struct
import sys
import threading
import time

import hid
import tkinter as tk
from tkinter import ttk, messagebox

READ_LEN = 256      # буфер чтения; на Windows он должен быть >= размера отчёта
MAX_PACKETS = 5000  # старше этого — удаляются из списка и памяти
POLL_MS = 100

# --- Палитра ---
BG      = "#1e1f26"   # фон окна
PANEL   = "#26272f"   # фон карточек / списков
PANEL2  = "#30313b"   # кнопки, заголовки
TITLEBG = "#33343f"   # заголовок области
HOVER   = "#3a3c48"   # наведение на кнопку
HL      = "#35508f"   # подсветка цели при перетаскивании / выделение
FG      = "#e4e5ea"   # основной текст
MUTED   = "#9aa0ab"   # вторичный текст
ACCENT  = "#5b8def"   # акцент (кнопка «Слушать»)
GREEN   = "#4cc38a"
ORANGE  = "#e8a04c"
SASHBG  = "#3a3b45"   # цвет разделителей между областями

FONT_MONO = ("Consolas", 10)
FONT_UI   = ("Segoe UI", 10)

# --- Строки интерфейса ---
STR = {
    "ru": {
        "app_title":      "HID Monitor",
        "btn_refresh":    "Обновить устройства",
        "btn_listen":     "Слушать",
        "btn_stop":       "Остановить",
        "btn_clear":      "Очистить пакеты",
        "title_devices":  "Устройства",
        "title_packets":  "Пакеты",
        "title_hex":      "HEX-дамп",
        "title_bytes":    "Расшифровка по байтам",
        "hint_devices":   "2×клик — слушать",
        "hint_packets":   "клик — разбор",
        "drag_tip":       "",
        "col_num":        "№",
        "col_time":       "Время",
        "col_dt":         "Δ, с",
        "col_len":        "Байт",
        "col_data":       "Данные (HEX)",
        "col_off":        "Смещ.",
        "col_hex":        "Hex",
        "col_dec":        "Dec",
        "col_bin":        "Bin",
        "col_ascii":      "Ascii",
        "col_note":       "Примечание",
        "copy":           "Копировать",
        "status_idle":    "Обновите список и выберите устройство",
        "status_devices": "Устройств: {n}. Выберите строку и нажмите «Слушать».",
        "status_listening": "Слушаю: {dev}",
        "status_stopped": "Прослушивание остановлено",
        "status_error":   "Ошибка чтения, остановлено: {err}",
        "open_failed":    "Не удалось открыть устройство",
        "info_packet":    "Пакет:",
        "info_time":      "Время:",
        "info_len":       "Длина:",
        "fmt_bytes":      "{n} байт",
        "prev_delta":     "(+{dt:.3f} с от предыдущего)",
        "hex_dump_title": "--- HEX-дамп ---",
        "interp_title":   "--- Интерпретации со смещения 1 (после report ID) ---",
        "report_id_note": "<- report ID (00 = не используется)",
        "changed_mark":   "* ИЗМЕНИЛСЯ",
    },
    "en": {
        "app_title":      "HID Monitor",
        "btn_refresh":    "Refresh devices",
        "btn_listen":     "Listen",
        "btn_stop":       "Stop",
        "btn_clear":      "Clear packets",
        "title_devices":  "Devices",
        "title_packets":  "Packets",
        "title_hex":      "HEX dump",
        "title_bytes":    "Byte decode",
        "hint_devices":   "dbl-click: listen",
        "hint_packets":   "click: decode",
        "drag_tip":       "Title bar: swap panels  ·  gutter: resize  ·  2×click on title: reset",
        "col_num":        "#",
        "col_time":       "Time",
        "col_dt":         "Δ, s",
        "col_len":        "Bytes",
        "col_data":       "Data (HEX)",
        "col_off":        "Offs.",
        "col_hex":        "Hex",
        "col_dec":        "Dec",
        "col_bin":        "Bin",
        "col_ascii":      "Ascii",
        "col_note":       "Note",
        "copy":           "Copy",
        "status_idle":    "Refresh the list and select a device",
        "status_devices": "Devices: {n}. Select a row and press \"Listen\".",
        "status_listening": "Listening: {dev}",
        "status_stopped": "Listening stopped",
        "status_error":   "Read error, stopped: {err}",
        "open_failed":    "Failed to open the device",
        "info_packet":    "Packet:",
        "info_time":      "Time:",
        "info_len":       "Length:",
        "fmt_bytes":      "{n} bytes",
        "prev_delta":     "(+{dt:.3f} s since previous)",
        "hex_dump_title": "--- HEX dump ---",
        "interp_title":   "--- Interpretations from offset 1 (after report ID) ---",
        "report_id_note": "<- report ID (00 = not used)",
        "changed_mark":   "* CHANGED",
    },
}

LANG_NAMES = [("ru", "Русский"), ("en", "English")]


def tr(lang, key, **kw):
    s = STR[lang].get(key, key)
    return s.format(**kw) if kw else s


def fmt_time(t):
    return time.strftime("%H:%M:%S", time.localtime(t)) + ".%03d" % int((t % 1) * 1000)


def device_label(info):
    name = info.get("product_string") or "(без имени)"
    mfr = info.get("manufacturer_string") or ""
    return "%04X:%04X  usage=%04X/%04X  iface=%d  %s %s" % (
        info["vendor_id"], info["product_id"],
        info.get("usage_page", 0), info.get("usage", 0),
        info.get("interface_number", -1),
        name, mfr,
    )


def hex_dump(data):
    lines = []
    for off in range(0, len(data), 16):
        chunk = data[off:off + 16]
        hexs = " ".join("%02X" % b for b in chunk)
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append("%04X  %-47s |%s|" % (off, hexs, asc))
    return "\n".join(lines)


def render_hex_info(pkt, prev, lang):
    """Область HEX-дампа: номер, время, длина, HEX-дамп, интерпретации.
    Возвращает список строк (текст, тег)."""
    data = pkt["data"]
    out = []
    add = lambda text, tag=None: out.append((text, tag))
    add("%-8s №%d" % (tr(lang, "info_packet"), pkt["num"]))
    add("%-8s %s  %s" % (tr(lang, "info_time"), fmt_time(pkt["t"]),
                         tr(lang, "prev_delta", dt=pkt["dt"])))
    add("%-8s %s" % (tr(lang, "info_len"), tr(lang, "fmt_bytes", n=len(data))))
    add("")
    add(tr(lang, "hex_dump_title"))
    for line in hex_dump(data).splitlines():
        add(line)
    add("")
    add(tr(lang, "interp_title"))
    for fmt, label in (("<H", "uint16 LE"), (">H", "uint16 BE"), ("<h", "int16 LE"),
                       ("<I", "uint32 LE"), (">I", "uint32 BE"), ("<i", "int32 LE"),
                       ("<f", "float32 LE"), (">f", "float32 BE")):
        size = struct.calcsize(fmt)
        if len(data) >= 1 + size:
            val = struct.unpack_from(fmt, data, 1)[0]
            add("  %-12s = %s" % (label, val), "note")
    payload = data[1:]
    if payload and all(32 <= b < 127 for b in payload):
        add("  %-12s = %r" % ("ASCII", payload.decode("ascii")), "note")
    return out


def render_bytes(pkt, prev, lang):
    """Таблица байтов: (off, hex, dec, bin, ascii, примечание, тег)."""
    data = pkt["data"]
    prev_data = prev["data"] if prev else None
    rows = []
    for off, b in enumerate(data):
        ch = chr(b) if 32 <= b < 127 else "."
        note, tag = "", None
        if prev_data is not None and (off >= len(prev_data) or prev_data[off] != b):
            note, tag = tr(lang, "changed_mark"), "changed"
        if off == 0:
            note = tr(lang, "report_id_note")
            tag = tag or "note"
        rows.append((off, "%02X" % b, b, format(b, "08b"), ch, note, tag))
    return rows


class App:
    def __init__(self, root):
        self.root = root
        root.minsize(720, 480)
        root.configure(bg=BG)

        loc = (locale.getlocale()[0] or "").lower()
        self.lang = "ru" if loc.startswith("ru") else "en"

        self.devices = []
        self.packets = []
        self.pkt_num = 0
        self.last_t = None
        self.dev = None
        self.thread = None
        self.stop_event = threading.Event()
        self.rx = queue.Queue()
        self.cur_pkt_i = None
        self._status_key = None
        self._status_kw = {}

        # раскладка
        self.panels = []            # все области (панели)
        self.panel_weight = {}      # id(panel) -> вес в panedwindow
        self._drag_panel = None
        self._hl_panel = None

        self._build_style()
        self._build_ui()

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(POLL_MS, self.poll)
        self.refresh_devices()

    def t(self, key, **kw):
        return tr(self.lang, key, **kw)

    # ---------- оформление ----------

    def _build_style(self):
        st = ttk.Style(self.root)
        st.theme_use("clam")

        st.configure(".", background=BG, foreground=FG, font=FONT_UI)
        st.configure("TFrame", background=BG)
        st.configure("Card.TFrame", background=PANEL)

        st.configure("Toolbar.TFrame", background=PANEL)
        st.configure("Statusbar.TFrame", background=PANEL)
        st.configure("Status.TLabel", background=PANEL, foreground=MUTED)

        st.configure("TButton", background=PANEL2, foreground=FG, borderwidth=0,
                     focusthickness=0, padding=(14, 6))
        st.map("TButton",
               background=[("active", HOVER), ("disabled", PANEL)],
               foreground=[("disabled", MUTED)])
        st.configure("Accent.TButton", background=ACCENT, foreground="white")
        st.map("Accent.TButton",
               background=[("active", "#6d9af2"), ("disabled", PANEL)],
               foreground=[("disabled", MUTED)])

        st.configure("Treeview", background=PANEL, fieldbackground=PANEL,
                     foreground=FG, borderwidth=0, rowheight=24)
        st.map("Treeview",
               background=[("selected", HL)],
               foreground=[("selected", "white")])
        st.configure("Treeview.Heading", background=PANEL2, foreground=MUTED,
                     relief="flat", font=("Segoe UI", 9, "bold"), padding=(6, 6))
        st.map("Treeview.Heading", background=[("active", HOVER)])

        st.configure("TPanedwindow", background=SASHBG)
        st.configure("Sash", sashthickness=8)

        st.configure("TCombobox", fieldbackground=PANEL2, background=PANEL2,
                     foreground=FG, arrowcolor=FG, borderwidth=0, padding=4)
        st.map("TCombobox",
               fieldbackground=[("readonly", PANEL2)],
               foreground=[("readonly", FG)],
               arrowcolor=[("readonly", FG)])
        self.root.option_add("*TCombobox*Listbox.background", PANEL2)
        self.root.option_add("*TCombobox*Listbox.foreground", FG)
        self.root.option_add("*TCombobox*Listbox.selectBackground", HL)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "white")

    def _vscroll(self, parent, widget):
        sb = tk.Scrollbar(parent, command=widget.yview,
                          bg=PANEL, troughcolor=PANEL, activebackground=HOVER,
                          borderwidth=0, highlightthickness=0)
        widget.config(yscrollcommand=sb.set)
        return sb

    def _make_gutter(self, pw, orient):
        """Собственный разделитель поверх саши panedwindow.

        Панели-области — дети корневого окна и перекрывают настоящий саш,
        поэтому мышь реального пользователя по нему не попадает. Поверх кладётся
        тонкая панель-желоб (выше всех окон), которая программно двигает саш.
        Возвращает (желоб, функция-перекладка)."""
        # вертикальный paned: граница горизонтальная, тянем вверх-вниз (↕);
        # горизонтальный paned: граница вертикальная, тянем влево-вправо (↔)
        arrow = "sb_v_double_arrow" if orient == tk.VERTICAL else "sb_h_double_arrow"
        g = tk.Frame(self.root, bg=SASHBG, cursor=arrow,
                     highlightthickness=0, bd=0)
        state = {}

        def layout():
            try:
                if len(pw.panes()) < 2:
                    g.place_forget()
                    return
                pos = pw.sashpos(0)
                px = pw.winfo_rootx() - self.root.winfo_rootx()
                py = pw.winfo_rooty() - self.root.winfo_rooty()
                if orient == tk.VERTICAL:
                    g.place(x=px, y=py + pos, width=pw.winfo_width(), height=8)
                else:
                    g.place(x=px + pos, y=py, width=8, height=pw.winfo_height())
                g.lift()
            except tk.TclError:
                pass

        def press(event):
            try:
                state["s0"] = pw.sashpos(0)
                state["c0"] = event.y_root if orient == tk.VERTICAL else event.x_root
            except tk.TclError:
                state.clear()

        def motion(event):
            if "s0" not in state:
                return
            c = event.y_root if orient == tk.VERTICAL else event.x_root
            try:
                pw.sashpos(0, max(0, state["s0"] + c - state["c0"]))
                layout()  # саш переместился — сразу перекладываем желоб
            except tk.TclError:
                pass

        g.bind("<ButtonPress-1>", press)
        g.bind("<B1-Motion>", motion)
        g.bind("<Enter>", lambda e: g.config(bg=HOVER))
        g.bind("<Leave>", lambda e: g.config(bg=SASHBG))
        pw.bind("<Configure>", lambda e: self.root.after_idle(layout))
        # перекладка и при изменении размеров панелей: после перестановки
        # областей саши пересчитываются позже нас
        for pane in pw.panes():
            self.root.nametowidget(str(pane)).bind(
                "<Configure>", lambda e: self.root.after_idle(layout))
        return g, layout

    def _update_gutters(self):
        for layout in self._gutter_layouts:
            layout()

    def _make_panel(self, title_key, hint_key=None, weight=1):
        """Область с заголовком-ручкой. Возвращает (панель, контейнер содержимого)."""
        p = ttk.Frame(self.root, style="Card.TFrame", padding=6)

        bar = tk.Frame(p, bg=TITLEBG, highlightthickness=0, cursor="fleur")
        bar.pack(fill=tk.X)
        grip = tk.Label(bar, text="⠿", bg=TITLEBG, fg=MUTED, font=("Segoe UI", 10))
        grip.pack(side=tk.LEFT, padx=(6, 2))
        lbl = tk.Label(bar, bg=TITLEBG, fg=FG, font=("Segoe UI", 9, "bold"),
                       anchor=tk.W, cursor="fleur")
        lbl.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=3)
        hint = tk.Label(bar, bg=TITLEBG, fg=MUTED, font=("Segoe UI", 8), cursor="fleur")
        hint.pack(side=tk.RIGHT, padx=6)
        if hint_key is None:
            hint.pack_forget()

        body = ttk.Frame(p, style="Card.TFrame")
        body.pack(fill=tk.BOTH, expand=True, pady=(6, 0))

        p._title_key = title_key
        p._hint_key = hint_key
        p._bar = bar
        p._bar_widgets = (bar, grip, lbl, hint)
        p._title_lbl = lbl
        p._hint = hint

        for w in p._bar_widgets:
            w.bind("<ButtonPress-1>", self.drag_start)
            w.bind("<B1-Motion>", self.drag_motion)
            w.bind("<ButtonRelease-1>", self.drag_drop)
            w.bind("<Double-Button-1>", lambda e: self.reset_layout())

        self.panels.append(p)
        self.panel_weight[id(p)] = weight
        return p, body

    def _build_ui(self):
        # --- Верхняя панель ---
        bar = ttk.Frame(self.root, style="Toolbar.TFrame", padding=(12, 8))
        bar.pack(fill=tk.X)
        self.btn_refresh = ttk.Button(bar, text=self.t("btn_refresh"),
                                      command=self.refresh_devices)
        self.btn_refresh.pack(side=tk.LEFT, padx=3)
        self.btn_listen = ttk.Button(bar, text=self.t("btn_listen"), style="Accent.TButton",
                                     command=self.toggle_listen, state=tk.DISABLED)
        self.btn_listen.pack(side=tk.LEFT, padx=3)
        self.btn_clear = ttk.Button(bar, text=self.t("btn_clear"), command=self.clear_packets)
        self.btn_clear.pack(side=tk.LEFT, padx=3)
        ttk.Label(bar, text=self.t("drag_tip"), style="Status.TLabel",
                  background=PANEL).pack(side=tk.LEFT, padx=16)

        langf = ttk.Frame(bar, style="Toolbar.TFrame")
        langf.pack(side=tk.RIGHT)
        self.lang_var = tk.StringVar(value=dict(LANG_NAMES)[self.lang])
        self.lang_box = ttk.Combobox(langf, textvariable=self.lang_var, state="readonly",
                                     width=11, values=[name for _, name in LANG_NAMES])
        self.lang_box.pack(side=tk.RIGHT)
        self.lang_box.bind("<<ComboboxSelected>>", self.on_lang_change)

        # --- Grid-layout: 2 колонки × 2 области, всё перетаскивается ---
        body = ttk.Frame(self.root, padding=10)
        body.pack(fill=tk.BOTH, expand=True)

        self.p_dev, dev_body = self._make_panel("title_devices", "hint_devices", weight=1)
        self.p_pkt, pkt_body = self._make_panel("title_packets", "hint_packets", weight=3)
        self.p_hex, hex_body = self._make_panel("title_hex", weight=2)
        self.p_bytes, bytes_body = self._make_panel("title_bytes", weight=3)

        self.v_left = ttk.Panedwindow(body, orient=tk.VERTICAL)
        self.v_right = ttk.Panedwindow(body, orient=tk.VERTICAL)
        self.main_paned = ttk.Panedwindow(body, orient=tk.HORIZONTAL)
        self.main_paned.pack(fill=tk.BOTH, expand=True)
        self.main_paned.add(self.v_left, weight=1)
        self.main_paned.add(self.v_right, weight=1)
        self.v_left.add(self.p_dev, weight=1)
        self.v_left.add(self.p_pkt, weight=3)
        self.v_right.add(self.p_hex, weight=2)
        self.v_right.add(self.p_bytes, weight=3)
        # карта «панель -> колонка», по ней идут перестановки
        self.panel_paned = {self.p_dev: self.v_left, self.p_pkt: self.v_left,
                            self.p_hex: self.v_right, self.p_bytes: self.v_right}
        # собственные разделители поверх сашей (саши перекрыты панелями)
        self._gutter_layouts = []
        self._gutters = []
        for pw, orient in ((self.v_left, tk.VERTICAL), (self.v_right, tk.VERTICAL),
                           (self.main_paned, tk.HORIZONTAL)):
            g, layout = self._make_gutter(pw, orient)
            self._gutters.append(g)
            self._gutter_layouts.append(layout)
        body.bind("<Configure>", lambda e: self.root.after_idle(self._update_gutters))

        # --- Содержимое областей ---
        dev_body.rowconfigure(0, weight=1)
        dev_body.columnconfigure(0, weight=1)
        self.dev_list = tk.Listbox(dev_body, height=5, exportselection=False,
                                   font=FONT_MONO, bg=PANEL, fg=FG, borderwidth=0,
                                   highlightthickness=0, relief=tk.FLAT,
                                   selectbackground=HL, selectforeground="white",
                                   activestyle="none")
        self.dev_list.grid(row=0, column=0, sticky=tk.NSEW)
        self._vscroll(dev_body, self.dev_list).grid(row=0, column=1, sticky=tk.NS)
        self.dev_list.bind("<<ListboxSelect>>", lambda e: self.btn_listen.config(state=tk.NORMAL))
        self.dev_list.bind("<Double-Button-1>", lambda e: self.toggle_listen())

        pkt_body.rowconfigure(0, weight=1)
        pkt_body.columnconfigure(0, weight=1)
        cols = ("num", "time", "dt", "len", "data")
        self.pkt_tree = ttk.Treeview(pkt_body, columns=cols, show="headings",
                                     selectmode="browse")
        panchors = {"num": tk.E, "time": tk.W, "dt": tk.E, "len": tk.E, "data": tk.W}
        pwidths = {"num": 60, "time": 110, "dt": 80, "len": 60, "data": 300}
        for c in cols:
            self.pkt_tree.column(c, width=pwidths[c], anchor=panchors[c],
                                 stretch=(c == "data"))
        self.pkt_tree.grid(row=0, column=0, sticky=tk.NSEW)
        self._vscroll(pkt_body, self.pkt_tree).grid(row=0, column=1, sticky=tk.NS)
        self.pkt_tree.bind("<<TreeviewSelect>>", self.on_select_packet)

        hex_body.rowconfigure(0, weight=1)
        hex_body.columnconfigure(0, weight=1)
        self.hex_text = tk.Text(hex_body, font=FONT_MONO, wrap=tk.NONE,
                                state=tk.DISABLED, bg=PANEL, fg=FG, borderwidth=0,
                                highlightthickness=0, relief=tk.FLAT,
                                selectbackground=HL, selectforeground="white")
        self.hex_text.grid(row=0, column=0, sticky=tk.NSEW)
        self._vscroll(hex_body, self.hex_text).grid(row=0, column=1, sticky=tk.NS)
        hsb = tk.Scrollbar(hex_body, command=self.hex_text.xview, orient=tk.HORIZONTAL,
                           bg=PANEL, troughcolor=PANEL, activebackground=HOVER,
                           borderwidth=0, highlightthickness=0)
        self.hex_text.config(xscrollcommand=hsb.set)
        hsb.grid(row=1, column=0, sticky=tk.EW)
        self.hex_text.tag_config("changed", foreground=ORANGE)
        self.hex_text.tag_config("note", foreground=MUTED)
        self.hex_menu = tk.Menu(self.hex_text, tearoff=0,
                                bg=PANEL2, fg=FG, activebackground=ACCENT,
                                activeforeground="white", borderwidth=0)
        self.hex_menu.add_command(command=self.copy_hex)
        self.hex_text.bind("<Button-3>", self.show_hex_menu)

        bytes_body.rowconfigure(0, weight=1)
        bytes_body.columnconfigure(0, weight=1)
        bcols = ("off", "hex", "dec", "bin", "ascii", "note")
        self.byte_tree = ttk.Treeview(bytes_body, columns=bcols, show="headings",
                                      selectmode="none")
        banchors = {"off": tk.E, "hex": tk.E, "dec": tk.E, "bin": tk.W,
                    "ascii": tk.W, "note": tk.W}
        bwidths = {"off": 60, "hex": 60, "dec": 60, "bin": 130, "ascii": 60, "note": 280}
        for c in bcols:
            self.byte_tree.column(c, width=bwidths[c], anchor=banchors[c],
                                  stretch=(c == "note"))
        self.byte_tree.tag_configure("changed", foreground=ORANGE)
        self.byte_tree.tag_configure("note", foreground=MUTED)
        self.byte_tree.grid(row=0, column=0, sticky=tk.NSEW)
        self._vscroll(bytes_body, self.byte_tree).grid(row=0, column=1, sticky=tk.NS)

        # --- Статус-панель ---
        statusbar = ttk.Frame(self.root, style="Statusbar.TFrame", padding=(12, 6))
        statusbar.pack(fill=tk.X, side=tk.BOTTOM)
        self.dot = tk.Label(statusbar, text="●", bg=PANEL, fg=MUTED, font=("Segoe UI", 10))
        self.dot.pack(side=tk.LEFT)
        self.status = tk.StringVar()
        ttk.Label(statusbar, textvariable=self.status, style="Status.TLabel").pack(
            side=tk.LEFT, padx=(8, 0))

        self.apply_language()
        self.root.after_idle(self._update_gutters)

    # ---------- перетаскивание областей ----------

    def _panel_of(self, widget):
        while widget is not None and widget is not self.root:
            if widget in self.panels:
                return widget
            widget = widget.master
        return None

    def _panel_at(self, x_root, y_root):
        w = self.root.winfo_containing(x_root, y_root)
        return self._panel_of(w) if w else None

    def _hl(self, panel):
        """Подсветка области-приёмника при перетаскивании."""
        if panel is self._hl_panel:
            return
        if self._hl_panel is not None:
            self._hl_panel._bar.config(bg=TITLEBG)
            self._hl_panel._title_lbl.config(bg=TITLEBG)
        self._hl_panel = panel
        if panel is not None:
            panel._bar.config(bg=HOVER)
            panel._title_lbl.config(bg=HOVER)

    def drag_start(self, event):
        self._drag_panel = self._panel_of(event.widget)

    def drag_motion(self, event):
        if self._drag_panel is None:
            return
        target = self._panel_at(event.x_root, event.y_root)
        if target is self._drag_panel:
            target = None
        self._hl(target)

    def drag_drop(self, event):
        self._hl(None)
        if self._drag_panel is None:
            return
        target = self._panel_at(event.x_root, event.y_root)
        if target is not None and target is not self._drag_panel:
            self.swap_panels(self._drag_panel, target)
        self._drag_panel = None

    def _panes_widgets(self, paned):
        return [self.root.nametowidget(str(w)) for w in paned.panes()]

    def _rebuild_paned(self, paned, widgets):
        for w in paned.panes():
            paned.forget(w)
        for w in widgets:
            paned.add(w, weight=self.panel_weight.get(id(w), 1))

    def swap_panels(self, a, b):
        """Меняет области a и b местами (внутри одной колонки или между колонками)."""
        pa, pb = self.panel_paned[a], self.panel_paned[b]
        if pa is pb:
            la = self._panes_widgets(pa)
            ia, ib = la.index(a), la.index(b)
            la[ia], la[ib] = la[ib], la[ia]
            self._rebuild_paned(pa, la)
        else:
            la = self._panes_widgets(pa)
            lb = self._panes_widgets(pb)
            ia, ib = la.index(a), lb.index(b)
            la[ia], lb[ib] = b, a
            self._rebuild_paned(pa, la)
            self._rebuild_paned(pb, lb)
            self.panel_paned[a], self.panel_paned[b] = pb, pa
        self.root.after_idle(self._update_gutters)

    def reset_layout(self):
        """Возвращает раскладку по умолчанию: слева устройства+пакеты, справа HEX+байты."""
        for v in (self.v_left, self.v_right):
            for w in v.panes():
                v.forget(w)
        self.v_left.add(self.p_dev, weight=self.panel_weight.get(id(self.p_dev), 1))
        self.v_left.add(self.p_pkt, weight=self.panel_weight.get(id(self.p_pkt), 3))
        self.v_right.add(self.p_hex, weight=self.panel_weight.get(id(self.p_hex), 2))
        self.v_right.add(self.p_bytes, weight=self.panel_weight.get(id(self.p_bytes), 3))
        self.panel_paned = {self.p_dev: self.v_left, self.p_pkt: self.v_left,
                            self.p_hex: self.v_right, self.p_bytes: self.v_right}
        self.root.after_idle(self._update_gutters)

    # ---------- язык ----------

    def _set_headings(self):
        for tree, mapping in (
            (self.pkt_tree, (("num", "col_num", tk.E), ("time", "col_time", tk.W),
                             ("dt", "col_dt", tk.E), ("len", "col_len", tk.E),
                             ("data", "col_data", tk.W))),
            (self.byte_tree, (("off", "col_off", tk.E), ("hex", "col_hex", tk.E),
                              ("dec", "col_dec", tk.E), ("bin", "col_bin", tk.W),
                              ("ascii", "col_ascii", tk.W), ("note", "col_note", tk.W))),
        ):
            for col, key, anchor in mapping:
                tree.heading(col, text=self.t(key), anchor=anchor)

    def apply_language(self):
        self.root.title(self.t("app_title"))
        self.btn_refresh.config(text=self.t("btn_refresh"))
        self.btn_listen.config(text=self.t("btn_stop") if self.dev is not None
                               else self.t("btn_listen"))
        self.btn_clear.config(text=self.t("btn_clear"))
        self.hex_menu.entryconfigure(0, label=self.t("copy"))
        for p in self.panels:
            p._title_lbl.config(text=self.t(p._title_key))
            if p._hint_key:
                p._hint.config(text=self.t(p._hint_key))
        self._set_headings()
        if self._status_key:
            self.status.set(self.t(self._status_key, **self._status_kw))
        if self.cur_pkt_i is not None and self.cur_pkt_i < len(self.packets):
            self.render_details(self.cur_pkt_i)

    def on_lang_change(self, _event):
        name = self.lang_var.get()
        for code, lang_name in LANG_NAMES:
            if lang_name == name:
                self.lang = code
                break
        self.apply_language()

    # ---------- детали ----------

    def show_hex_menu(self, event):
        try:
            self.hex_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.hex_menu.grab_release()

    def copy_hex(self):
        try:
            text = self.hex_text.get("sel.first", "sel.last")
        except tk.TclError:
            text = self.hex_text.get("1.0", tk.END)
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    def render_details(self, i):
        pkt = self.packets[i]
        prev = self.packets[i - 1] if i > 0 else None
        self.hex_text.config(state=tk.NORMAL)
        self.hex_text.delete("1.0", tk.END)
        for text, tag in render_hex_info(pkt, prev, self.lang):
            self.hex_text.insert(tk.END, text + "\n", tag or ())
        self.hex_text.tag_remove(tk.SEL, "1.0", tk.END)
        self.hex_text.see("1.0")
        self.hex_text.config(state=tk.DISABLED)

        self.byte_tree.delete(*self.byte_tree.get_children())
        for off, hx, dec, bn, ch, note, tag in render_bytes(pkt, prev, self.lang):
            self.byte_tree.insert("", tk.END,
                                  values=(off, hx, dec, bn, ch, note),
                                  tags=(tag or ()))

    # ---------- логика ----------

    def set_status(self, key, **kw):
        self._status_key = key
        self._status_kw = kw
        self.status.set(self.t(key, **kw))

    def refresh_devices(self):
        self.devices = list(hid.enumerate())
        self.dev_list.delete(0, tk.END)
        for info in self.devices:
            self.dev_list.insert(tk.END, device_label(info))
        self.set_status("status_devices", n=len(self.devices))

    def toggle_listen(self):
        if self.dev is not None:
            self.stop_listen()
            return
        sel = self.dev_list.curselection()
        if not sel:
            return
        info = self.devices[sel[0]]
        dev = hid.device()
        try:
            dev.open_path(info["path"])
        except Exception as exc:
            messagebox.showerror(self.t("app_title"),
                                 self.t("open_failed") + ":\n%s" % exc)
            return
        self.dev = dev
        self.stop_event.clear()
        self.thread = threading.Thread(target=self.read_worker, daemon=True)
        self.thread.start()
        self.btn_listen.config(text=self.t("btn_stop"))
        self.dot.config(fg=GREEN)
        self.set_status("status_listening", dev=device_label(info))

    def read_worker(self):
        while not self.stop_event.is_set():
            try:
                buf = self.dev.read(READ_LEN, timeout_ms=200)
            except Exception as exc:
                self.rx.put(("error", str(exc)))
                return
            if buf:
                self.rx.put(("data", bytes(buf)))

    def stop_listen(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=1.0)
            self.thread = None
        if self.dev:
            try:
                self.dev.close()
            except Exception:
                pass
            self.dev = None
        self.btn_listen.config(text=self.t("btn_listen"))
        self.dot.config(fg=MUTED)
        self.set_status("status_stopped")

    def poll(self):
        try:
            while True:
                kind, payload = self.rx.get_nowait()
                if kind == "data":
                    self.add_packet(payload)
                else:
                    self.set_status("status_error", err=payload)
                    self.stop_listen()
        except queue.Empty:
            pass
        self.root.after(POLL_MS, self.poll)

    def add_packet(self, data):
        t = time.time()
        self.pkt_num += 1
        pkt = {"num": self.pkt_num, "t": t,
               "dt": 0.0 if self.last_t is None else t - self.last_t, "data": data}
        self.last_t = t
        self.packets.append(pkt)
        if len(self.packets) > MAX_PACKETS:
            self.packets.pop(0)
            first = self.pkt_tree.get_children()[0]
            self.pkt_tree.delete(first)
        preview = " ".join("%02X" % b for b in data[:10])
        if len(data) > 10:
            preview += " ..."
        self.pkt_tree.insert("", tk.END, values=(
            pkt["num"], fmt_time(t), "%.3f" % pkt["dt"], len(data), preview))
        self.pkt_tree.yview_moveto(1.0)

    def on_select_packet(self, _event):
        sel = self.pkt_tree.selection()
        if not sel:
            return
        self.cur_pkt_i = self.pkt_tree.index(sel[0])
        self.render_details(self.cur_pkt_i)

    def clear_packets(self):
        self.packets.clear()
        self.pkt_num = 0
        self.last_t = None
        self.cur_pkt_i = None
        for item in self.pkt_tree.get_children():
            self.pkt_tree.delete(item)
        self.hex_text.config(state=tk.NORMAL)
        self.hex_text.delete("1.0", tk.END)
        self.hex_text.config(state=tk.DISABLED)
        self.byte_tree.delete(*self.byte_tree.get_children())

    def on_close(self):
        self.stop_listen()
        self.root.destroy()


def main():
    selftest = "--selftest" in sys.argv
    root = tk.Tk()
    if selftest:
        root.withdraw()
    app = App(root)
    if selftest:
        root.update()
        print("SELFTEST OK, devices:", len(app.devices))
        root.destroy()
    else:
        root.mainloop()


if __name__ == "__main__":
    main()
