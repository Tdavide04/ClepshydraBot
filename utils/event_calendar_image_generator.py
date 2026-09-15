"""
event_calendar_image_generator.py

Disegna, per un singolo mese, l'immagine del calendario eventi Arena a
partire dai dati gia' strutturati da
`utils.arena_event_schedule.build_month_calendar()`
({categoria: [(giorno_inizio, giorno_fine, nome_evento), ...]}).

`create_month_calendar()` (usata in produzione) e' un Gantt con una riga per
SINGOLA CATEGORIA (come le pagine Wizards le elencano, 13-15 righe - non
fuse per famiglia), colorato per famiglia e con nomi puliti nelle barre,
seguito da un elenco testuale dettagliato sotto, raggruppato per famiglia,
con il nome completo di ogni evento e la categoria originale tra parentesi.
E' il risultato di tre giri di iterazione con mock-up sui dati reali:
- una griglia calendario classica (un blocco di testo per categoria attiva
  in ogni cella giorno) e' illeggibile perche' 4-6 categorie restano attive
  per settimane e si ripetono identiche in ogni cella, spingendo fuori
  vista (dietro un "+N altri") gli eventi che cambiano giorno per giorno;
- un tentativo con fascia "always-on" + griglia per il resto migliorava ma
  il testo restava troncato nelle celle strette (~160px) per i nomi lunghi;
- uno swimlane con una riga per FAMIGLIA (6 righe, niente testo nelle
  barre, dettaglio in un elenco sotto) risolveva il troncamento ma perdeva
  la granularita' per singola categoria (es. non si vedeva piu' a colpo
  d'occhio che "Pick-Two Draft" e "Traditional Draft" sono davvero due code
  distinte, non la stessa cosa disegnata due volte) - il design finale
  riporta una riga per categoria nel Gantt (come nel primo tentativo,
  create_month_panel) ma ne eredita le lezioni successive: colore per
  famiglia invece che ciclico, nomi puliti (_clean_name) invece che grezzi,
  e l'elenco dettagliato sotto (ispirato a arpgseasons.com/en/calendar, un
  calendario di stagioni di giochi ARPG concorrenti con lo stesso problema
  di serie temporali sovrapposte) per i casi in cui anche con nomi puliti
  il testo non entra nella barra;
- i colori sono raggruppati per famiglia (non un colore per singola
  categoria) perche' con 13-15 categorie una palette 1:1 non da' un pattern
  riconoscibile a colpo d'occhio; la classificazione per famiglia e'
  un'euristica su parole chiave nel nome categoria (_classify_family), non
  un dato che arriva dalla pagina Wizards. Colori scelti a mano su richiesta
  esplicita (non ciclici).

`create_month_panel()` (il design originario, palette ciclica per categoria
e nomi grezzi) resta nel modulo com'e' - nessun comando lo richiama piu', ma
nessuna ragione per buttare via del codice funzionante nel caso serva di
nuovo un confronto.
"""

import calendar as calendar_module
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from utils.arena_event_schedule import MONTHS_IT


class EventCalendarImageGenerator:

    PADDING_X = 40
    PADDING_TOP = 74
    PADDING_BOTTOM = 24

    ROW_LABEL_WIDTH = 190
    DAY_COL_WIDTH = 32
    # Altezza di una singola "corsia" all'interno di una riga categoria. Una
    # categoria con eventi che si sovrappongono in data (es. "Other Events",
    # che nella pagina reale ospita piu' esibizioni parallele nello stesso
    # periodo) occupa piu' corsie impilate verticalmente invece di comprimere
    # le barre una sopra l'altra - senza questo, testi ed etichette di eventi
    # diversi si sovrappongono nello stesso spazio, illeggibili.
    LANE_HEIGHT = 38
    BAR_HEIGHT = 26

    HEADER_HEIGHT = 26

    BG_COLOR = (18, 20, 30)
    GRID_COLOR = (50, 54, 68)
    GRID_COLOR_STRONG = (75, 80, 98)
    TEXT_PRIMARY = (230, 230, 235)
    TEXT_SECONDARY = (160, 160, 175)
    BAR_TEXT_COLOR = (18, 18, 22)
    ROW_LABEL_BG = (26, 28, 40)

    TITLE_FONT_SIZE = 26
    DAY_FONT_SIZE = 12
    ROW_LABEL_FONT_SIZE = 14
    BAR_FONT_SIZE = 12

    # Palette ciclica per categoria - assegnata per indice, non per hash del
    # nome, cosi' l'ordine (stabile: viene da un dict Python) resta coerente
    # tra un rendering e il successivo per lo stesso set di categorie.
    CATEGORY_COLORS = [
        (99, 179, 237),
        (246, 173, 85),
        (154, 230, 180),
        (245, 101, 101),
        (183, 148, 244),
        (250, 240, 137),
        (129, 230, 217),
        (252, 129, 192),
    ]

    # ── Costanti elenco dettagliato (sotto il Gantt) ──
    DETAIL_LINE_HEIGHT = 20
    DETAIL_HEADING_HEIGHT = 24
    DETAIL_GROUP_GAP = 10
    DETAIL_HEADING_FONT_SIZE = 13
    DETAIL_ITEM_FONT_SIZE = 12
    DETAIL_ITEM_COLOR = (170, 172, 185)
    DETAIL_CATEGORY_MAX_CHARS = 40

    # Raggruppamento colore per famiglia (non per singola categoria): con
    # 13-15 categorie una palette 1:1 non da' un pattern riconoscibile a
    # colpo d'occhio. Euristica su parole chiave nel nome, non un dato che
    # arriva dalla pagina Wizards - vedi _classify_family(). Colori scelti a
    # mano (non ciclici) su richiesta esplicita.
    FAMILY_COLORS = {
        "Premier Draft": (66, 133, 220),
        "Quick Draft": (67, 176, 108),
        "Flashback": (149, 105, 210),
        "Sealed & Cube": (108, 201, 230),
        "Metagame": (226, 140, 57),
        "Community": (222, 68, 68),
    }

    # Ordine fisso per righe fascia e legenda, cosi' non dipende dall'ordine
    # (non deterministico ai fini nostri) con cui le categorie compaiono
    # nella pagina Wizards.
    FAMILY_ORDER = [
        "Premier Draft", "Quick Draft", "Flashback",
        "Sealed & Cube", "Metagame", "Community",
    ]

    # Prefissi da rimuovere dal nome evento mostrato in barre/pillole: la
    # categoria (colore) gia' comunica "che tipo di evento e'", quindi
    # ripetere "Magic: The Gathering" o "Arena Direct for" nel testo e'
    # rumore puro - vedi _clean_name().
    _ARENA_DIRECT_PREFIX = "arena direct for "
    _MTG_PREFIX = "magic: the gathering | "

    # Usata nell'elenco dettagliato quando piu' mesi condividono lo stesso
    # elenco (create_multi_month_calendar) - senza il mese, "11-19" di
    # agosto e "11-19" di settembre sarebbero indistinguibili una volta
    # unite nella stessa sezione famiglia.
    MONTH_ABBR_IT = {
        1: "gen", 2: "feb", 3: "mar", 4: "apr", 5: "mag", 6: "giu",
        7: "lug", 8: "ago", 9: "set", 10: "ott", 11: "nov", 12: "dic",
    }

    @classmethod
    def _try_font(cls, size, bold=False):
        names = [
            "arialbd.ttf" if bold else "arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold
            else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]
        for name in names:
            try:
                return ImageFont.truetype(name, size)
            except Exception:
                continue
        return ImageFont.load_default()

    @classmethod
    def create_month_panel(
        cls,
        year: int,
        month: int,
        last_day: int,
        category_entries: dict[str, list[tuple[int, int, str]]],
    ) -> BytesIO:
        """Disegna il pannello Gantt di un mese. `category_entries` e' gia'
        ritagliato ai limiti del mese da build_month_calendar() - questa
        funzione si limita a posizionare barre/testo, senza logica di date."""

        categories = list(category_entries.keys())

        # Pre-pass: per ogni categoria calcola su quale corsia va ciascun
        # evento (interval scheduling greedy) e quante corsie servono in
        # totale - determina l'altezza della riga PRIMA di disegnare.
        lanes_by_category: dict[str, list[int]] = {}
        lane_count_by_category: dict[str, int] = {}
        for category, entries in category_entries.items():
            assignment, n_lanes = cls._assign_lanes(entries)
            lanes_by_category[category] = assignment
            lane_count_by_category[category] = n_lanes

        row_heights = [lane_count_by_category[c] * cls.LANE_HEIGHT for c in categories]

        chart_width = last_day * cls.DAY_COL_WIDTH
        canvas_width = cls.PADDING_X + cls.ROW_LABEL_WIDTH + chart_width + cls.PADDING_X
        chart_height = sum(row_heights)
        canvas_height = cls.PADDING_TOP + cls.HEADER_HEIGHT + chart_height + cls.PADDING_BOTTOM

        canvas = Image.new("RGB", (canvas_width, canvas_height), cls.BG_COLOR)
        draw = ImageDraw.Draw(canvas)

        font_title = cls._try_font(cls.TITLE_FONT_SIZE, bold=True)
        font_day = cls._try_font(cls.DAY_FONT_SIZE)
        font_label = cls._try_font(cls.ROW_LABEL_FONT_SIZE, bold=True)
        font_bar = cls._try_font(cls.BAR_FONT_SIZE)

        # ── Titolo ──────────────────────────────────────────────
        title = f"{MONTHS_IT.get(month, month)} {year}"
        draw.text((cls.PADDING_X, 20), title, fill=cls.TEXT_PRIMARY, font=font_title)

        chart_x = cls.PADDING_X + cls.ROW_LABEL_WIDTH
        chart_y = cls.PADDING_TOP + cls.HEADER_HEIGHT

        # ── Header giorni ───────────────────────────────────────
        for day in range(1, last_day + 1):
            x = chart_x + (day - 1) * cls.DAY_COL_WIDTH
            draw.text(
                (x + cls.DAY_COL_WIDTH / 2, cls.PADDING_TOP + cls.HEADER_HEIGHT / 2),
                str(day),
                fill=cls.TEXT_SECONDARY,
                font=font_day,
                anchor="mm",
            )
            is_week_boundary = day % 7 == 1
            line_color = cls.GRID_COLOR_STRONG if is_week_boundary else cls.GRID_COLOR
            draw.line(
                [(x, chart_y), (x, chart_y + chart_height)],
                fill=line_color,
                width=1,
            )
        draw.line(
            [(chart_x + chart_width, chart_y), (chart_x + chart_width, chart_y + chart_height)],
            fill=cls.GRID_COLOR_STRONG,
            width=1,
        )

        # ── Righe categoria + barre ─────────────────────────────
        row_y = chart_y
        for row_idx, category in enumerate(categories):
            row_height = row_heights[row_idx]
            color = cls.CATEGORY_COLORS[row_idx % len(cls.CATEGORY_COLORS)]
            lane_assignment = lanes_by_category[category]

            draw.rectangle(
                [cls.PADDING_X, row_y, chart_x, row_y + row_height],
                fill=cls.ROW_LABEL_BG,
            )
            draw.text(
                (cls.PADDING_X + 10, row_y + row_height / 2),
                category,
                fill=cls.TEXT_PRIMARY,
                font=font_label,
                anchor="lm",
            )
            draw.line(
                [(cls.PADDING_X, row_y + row_height), (chart_x + chart_width, row_y + row_height)],
                fill=cls.GRID_COLOR,
                width=1,
            )

            for entry_idx, (day_start, day_end, name) in enumerate(category_entries[category]):
                lane_y = row_y + lane_assignment[entry_idx] * cls.LANE_HEIGHT
                bar_x1 = chart_x + (day_start - 1) * cls.DAY_COL_WIDTH
                bar_x2 = chart_x + day_end * cls.DAY_COL_WIDTH
                bar_y1 = lane_y + (cls.LANE_HEIGHT - cls.BAR_HEIGHT) / 2
                bar_y2 = bar_y1 + cls.BAR_HEIGHT

                draw.rounded_rectangle(
                    [bar_x1 + 2, bar_y1, bar_x2 - 2, bar_y2],
                    radius=5,
                    fill=color,
                )

                bar_width = bar_x2 - bar_x1 - 4
                label = cls._fit_text(draw, name, font_bar, bar_width - 10)
                if label:
                    draw.text(
                        ((bar_x1 + bar_x2) / 2, (bar_y1 + bar_y2) / 2),
                        label,
                        fill=cls.BAR_TEXT_COLOR,
                        font=font_bar,
                        anchor="mm",
                    )

            row_y += row_height

        output = BytesIO()
        canvas.save(output, format="PNG", optimize=True)
        output.seek(0)
        return output

    # Spazio verticale tra un pannello mese e il successivo quando piu' mesi
    # vengono composti in una sola immagine (create_multi_month_calendar).
    MULTI_MONTH_GAP = 40

    @classmethod
    def create_multi_month_calendar(
        cls,
        months: list[tuple[int, int, dict[str, list[tuple[int, int, str]]]]],
    ) -> BytesIO:
        """Compone in un'unica immagine un Gantt per ciascun mese, seguiti da
        UN SOLO elenco dettagliato che unisce le entry di tutti i mesi
        (raggruppato per famiglia, con il mese indicato su ogni riga per
        distinguere "11-19 ago" da "11-19 set") - invece di ripetere un
        elenco identico in struttura sotto ogni singolo pannello."""

        gantt_imgs = []
        combined_family_detail: dict[str, list[tuple[int, int, int, str, str]]] = {}

        for year, month, category_entries in months:
            cleaned_entries = cls._clean_category_entries(category_entries)
            gantt_imgs.append(cls._render_gantt_panel(year, month, cleaned_entries))

            month_detail = cls._build_family_detail(month, cleaned_entries)
            for family, entries in month_detail.items():
                combined_family_detail.setdefault(family, []).extend(entries)

        gantt_stack = cls._stack_vertically(gantt_imgs, gap=cls.MULTI_MONTH_GAP)
        detail_img = cls._render_detail_section(
            combined_family_detail, width=gantt_stack.width, show_month=True
        )
        canvas = cls._stack_vertically([gantt_stack, detail_img], gap=30)

        output = BytesIO()
        canvas.save(output, format="PNG", optimize=True)
        output.seek(0)
        return output

    @classmethod
    def _assign_lanes(cls, entries: list[tuple[int, int, str]]) -> tuple[list[int], int]:
        """Interval scheduling greedy: assegna a ciascun evento (per indice
        originale, non riordinato) la prima corsia libera - una corsia e'
        libera se il suo ultimo evento piazzato finisce prima che questo
        inizi. Restituisce (corsia_per_indice, numero_corsie_totali)."""

        order = sorted(range(len(entries)), key=lambda i: entries[i][0])
        lane_last_end: list[int] = []
        assignment = [0] * len(entries)

        for idx in order:
            day_start, day_end, _name = entries[idx]
            placed_lane = None
            for lane_idx, last_end in enumerate(lane_last_end):
                if last_end < day_start:
                    placed_lane = lane_idx
                    break
            if placed_lane is None:
                placed_lane = len(lane_last_end)
                lane_last_end.append(day_end)
            else:
                lane_last_end[placed_lane] = day_end
            assignment[idx] = placed_lane

        return assignment, max(1, len(lane_last_end))

    @classmethod
    def _fit_text(cls, draw: ImageDraw.ImageDraw, text: str, font, max_width: float) -> str:
        """Troncamento con ellissi se il nome evento non entra nella barra."""
        if max_width <= 0:
            return ""
        if draw.textlength(text, font=font) <= max_width:
            return text
        truncated = text
        while truncated and draw.textlength(truncated + "…", font=font) > max_width:
            truncated = truncated[:-1]
        return f"{truncated}…" if truncated else ""

    # ==========================================
    # GRIGLIA SETTIMANALE + FASCIA "ALWAYS-ON"
    # ==========================================

    @classmethod
    def _classify_family(cls, category: str) -> str:
        """Euristica su parole chiave nel nome categoria - non un dato che
        arriva dalla pagina Wizards. L'ordine dei controlli conta:
        - "Flashback Premier Draft" contiene sia "flashback" che "draft":
          Flashback va controllato prima, altrimenti finirebbe in Draft.
        - "September Format: ... Sealed" contiene sia "format" che
          "sealed": e' un evento a tempo/metagame (come Arena Direct), non
          un Sealed vero e proprio, quindi Metagame va controllato prima di
          Sealed & Cube.
        - "Quick Draft" contiene "draft": va controllato prima del
          catch-all generico "draft" (Premier/Pick-Two/Traditional/
          Contender Draft)."""

        lowered = category.lower()
        if "flashback" in lowered:
            return "Flashback"
        if "metagame" in lowered or "arena direct" in lowered or "format:" in lowered:
            return "Metagame"
        if "cube" in lowered or "sealed" in lowered:
            return "Sealed & Cube"
        if "quick draft" in lowered:
            return "Quick Draft"
        if "draft" in lowered:
            return "Premier Draft"
        return "Community"

    @classmethod
    def _clean_name(cls, name: str) -> str:
        """Rimuove i prefissi "Arena Direct for " e "Magic: The Gathering | "
        dal nome evento - il colore (famiglia) gia' comunica il tipo, quindi
        ripeterlo nel testo (es. "Arena Direct for Magic: The Gathering | The
        Hobbit") era solo rumore rispetto a mostrare la sola espansione
        ("The Hobbit")."""

        text = name.strip()
        if text.lower().startswith(cls._ARENA_DIRECT_PREFIX):
            text = text[len(cls._ARENA_DIRECT_PREFIX):]
        if text.lower().startswith(cls._MTG_PREFIX):
            text = text[len(cls._MTG_PREFIX):]
        return text.strip()

    @classmethod
    def _clean_category_entries(
        cls, category_entries: dict[str, list[tuple[int, int, str]]]
    ) -> dict[str, list[tuple[int, int, str]]]:
        return {
            category: [(ds, de, cls._clean_name(name)) for ds, de, name in entries]
            for category, entries in category_entries.items()
        }

    @classmethod
    def _render_gantt_panel(
        cls,
        year: int,
        month: int,
        cleaned_entries: dict[str, list[tuple[int, int, str]]],
    ) -> Image.Image:
        """Disegna il solo Gantt di un mese (titolo + una riga per
        categoria, colorata per famiglia, nomi puliti) - senza elenco
        dettagliato, cosi' puo' essere composto con quello di altri mesi
        prima di aggiungere un'unica sezione dettaglio in fondo."""

        last_day = calendar_module.monthrange(year, month)[1]
        categories = list(cleaned_entries.keys())

        lanes_by_category: dict[str, list[int]] = {}
        lane_count_by_category: dict[str, int] = {}
        for category, entries in cleaned_entries.items():
            assignment, n_lanes = cls._assign_lanes(entries)
            lanes_by_category[category] = assignment
            lane_count_by_category[category] = n_lanes

        row_heights = [lane_count_by_category[c] * cls.LANE_HEIGHT for c in categories]
        chart_width = last_day * cls.DAY_COL_WIDTH
        chart_height = sum(row_heights)
        canvas_width = cls.PADDING_X + cls.ROW_LABEL_WIDTH + chart_width + cls.PADDING_X
        canvas_height = cls.PADDING_TOP + cls.HEADER_HEIGHT + chart_height + cls.PADDING_BOTTOM

        canvas = Image.new("RGB", (canvas_width, canvas_height), cls.BG_COLOR)
        draw = ImageDraw.Draw(canvas)

        font_title = cls._try_font(cls.TITLE_FONT_SIZE, bold=True)
        font_day = cls._try_font(cls.DAY_FONT_SIZE)
        font_label = cls._try_font(cls.ROW_LABEL_FONT_SIZE, bold=True)
        font_bar = cls._try_font(cls.BAR_FONT_SIZE)

        title = f"{MONTHS_IT.get(month, month)} {year}"
        draw.text((cls.PADDING_X, 20), title, fill=cls.TEXT_PRIMARY, font=font_title)

        chart_x = cls.PADDING_X + cls.ROW_LABEL_WIDTH
        chart_y = cls.PADDING_TOP + cls.HEADER_HEIGHT

        # ── Header giorni + griglia verticale ──
        for day in range(1, last_day + 1):
            x = chart_x + (day - 1) * cls.DAY_COL_WIDTH
            draw.text(
                (x + cls.DAY_COL_WIDTH / 2, cls.PADDING_TOP + cls.HEADER_HEIGHT / 2),
                str(day),
                fill=cls.TEXT_SECONDARY,
                font=font_day,
                anchor="mm",
            )
            is_week_boundary = day % 7 == 1
            line_color = cls.GRID_COLOR_STRONG if is_week_boundary else cls.GRID_COLOR
            draw.line([(x, chart_y), (x, chart_y + chart_height)], fill=line_color, width=1)
        draw.line(
            [(chart_x + chart_width, chart_y), (chart_x + chart_width, chart_y + chart_height)],
            fill=cls.GRID_COLOR_STRONG,
            width=1,
        )

        # ── Righe categoria + barre (colore per famiglia, nomi puliti) ──
        row_y = chart_y
        for row_idx, category in enumerate(categories):
            row_height = row_heights[row_idx]
            color = cls.FAMILY_COLORS[cls._classify_family(category)]
            lane_assignment = lanes_by_category[category]

            draw.rectangle([cls.PADDING_X, row_y, chart_x, row_y + row_height], fill=cls.ROW_LABEL_BG)
            draw.text(
                (cls.PADDING_X + 10, row_y + row_height / 2),
                category,
                fill=cls.TEXT_PRIMARY,
                font=font_label,
                anchor="lm",
            )
            draw.line(
                [(cls.PADDING_X, row_y + row_height), (chart_x + chart_width, row_y + row_height)],
                fill=cls.GRID_COLOR,
                width=1,
            )

            for entry_idx, (day_start, day_end, name) in enumerate(cleaned_entries[category]):
                lane_y = row_y + lane_assignment[entry_idx] * cls.LANE_HEIGHT
                bar_x1 = chart_x + (day_start - 1) * cls.DAY_COL_WIDTH
                bar_x2 = chart_x + day_end * cls.DAY_COL_WIDTH
                bar_y1 = lane_y + (cls.LANE_HEIGHT - cls.BAR_HEIGHT) / 2
                bar_y2 = bar_y1 + cls.BAR_HEIGHT

                draw.rounded_rectangle([bar_x1 + 2, bar_y1, bar_x2 - 2, bar_y2], radius=5, fill=color)

                bar_width = bar_x2 - bar_x1 - 4
                label = cls._fit_text(draw, name, font_bar, bar_width - 10)
                if label:
                    draw.text(
                        ((bar_x1 + bar_x2) / 2, (bar_y1 + bar_y2) / 2),
                        label,
                        fill=(255, 255, 255),
                        font=font_bar,
                        anchor="mm",
                    )

            row_y += row_height

        return canvas

    @classmethod
    def _build_family_detail(
        cls,
        month: int,
        cleaned_entries: dict[str, list[tuple[int, int, str]]],
    ) -> dict[str, list[tuple[int, int, int, str, str]]]:
        """Raggruppa le entry (gia' pulite) per famiglia, per l'elenco
        dettagliato. Ogni entry porta con se' il mese (anche per un singolo
        mese) cosi' _render_detail_section puo' unire piu' mesi senza dover
        rifare il lavoro di classificazione/pulizia categoria."""

        family_detail: dict[str, list[tuple[int, int, int, str, str]]] = {}
        for category, entries in cleaned_entries.items():
            family = cls._classify_family(category)
            clean_category = cls._clean_name(category)
            # Alcuni nomi categoria (es. "September Format: Magic: The
            # Gathering | The Hobbit Sealed") non iniziano col prefisso che
            # _clean_name() rimuove, quindi restano lunghi - troncamento
            # difensivo a carattere (non a pixel: e' testo secondario tra
            # parentesi nell'elenco dettagliato, non serve precisione).
            if len(clean_category) > cls.DETAIL_CATEGORY_MAX_CHARS:
                clean_category = clean_category[:cls.DETAIL_CATEGORY_MAX_CHARS - 1].rstrip() + "…"

            bucket = family_detail.setdefault(family, [])
            for day_start, day_end, name in entries:
                bucket.append((month, day_start, day_end, name, clean_category))

        return family_detail

    @classmethod
    def _render_detail_section(
        cls,
        family_detail: dict[str, list[tuple[int, int, int, str, str]]],
        width: int,
        show_month: bool,
    ) -> Image.Image:
        """Disegna l'elenco dettagliato (nomi completi, nessun troncamento),
        raggruppato per famiglia. `show_month` va a True quando la sezione
        unisce piu' mesi (create_multi_month_calendar) - senza, "11-19" di
        mesi diversi sarebbero indistinguibili una volta unite le liste."""

        families_present = [f for f in cls.FAMILY_ORDER if f in family_detail]

        detail_rows: list[tuple[str, str]] = []  # ("heading"|"item", testo)
        for family in families_present:
            detail_rows.append(("heading", family))
            for month, day_start, day_end, name, clean_category in sorted(family_detail[family]):
                date_label = str(day_start) if day_start == day_end else f"{day_start}-{day_end}"
                if show_month:
                    date_label += f" {cls.MONTH_ABBR_IT.get(month, month)}"
                detail_rows.append(("item", f"{date_label}: {name}  ({clean_category})"))

        detail_height = sum(
            cls.DETAIL_HEADING_HEIGHT if kind == "heading" else cls.DETAIL_LINE_HEIGHT
            for kind, _ in detail_rows
        ) + cls.DETAIL_GROUP_GAP * len(families_present)

        canvas = Image.new("RGB", (width, detail_height), cls.BG_COLOR)
        draw = ImageDraw.Draw(canvas)

        font_heading = cls._try_font(cls.DETAIL_HEADING_FONT_SIZE, bold=True)
        font_item = cls._try_font(cls.DETAIL_ITEM_FONT_SIZE)

        y = 0
        for kind, text in detail_rows:
            if kind == "heading":
                color = cls.FAMILY_COLORS[text]
                draw.rounded_rectangle([cls.PADDING_X, y + 4, cls.PADDING_X + 12, y + 16], radius=3, fill=color)
                draw.text((cls.PADDING_X + 20, y), text, fill=cls.TEXT_PRIMARY, font=font_heading)
                y += cls.DETAIL_HEADING_HEIGHT
            else:
                draw.text((cls.PADDING_X + 28, y), text, fill=cls.DETAIL_ITEM_COLOR, font=font_item)
                y += cls.DETAIL_LINE_HEIGHT

        return canvas

    @classmethod
    def _stack_vertically(cls, images: list[Image.Image], gap: int) -> Image.Image:
        width = max(img.width for img in images)
        height = sum(img.height for img in images) + gap * (len(images) - 1)
        canvas = Image.new("RGB", (width, height), cls.BG_COLOR)
        y = 0
        for img in images:
            canvas.paste(img, (0, y))
            y += img.height + gap
        return canvas

    @classmethod
    def create_month_calendar(
        cls,
        year: int,
        month: int,
        category_entries: dict[str, list[tuple[int, int, str]]],
    ) -> BytesIO:
        """Gantt una riga per categoria (colorata per famiglia, nomi puliti)
        + elenco dettagliato sotto (nomi completi, categoria tra parentesi) -
        vedi il docstring di modulo per il percorso di iterazione che ha
        portato a questo design."""

        cleaned_entries = cls._clean_category_entries(category_entries)

        gantt_img = cls._render_gantt_panel(year, month, cleaned_entries)
        family_detail = cls._build_family_detail(month, cleaned_entries)
        detail_img = cls._render_detail_section(family_detail, width=gantt_img.width, show_month=False)

        canvas = cls._stack_vertically([gantt_img, detail_img], gap=30)

        output = BytesIO()
        canvas.save(output, format="PNG", optimize=True)
        output.seek(0)
        return output
