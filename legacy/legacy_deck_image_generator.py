from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
from io import BytesIO
import aiohttp
import math


class DeckImageGenerator:

    CARD_WIDTH = 146
    CARD_HEIGHT = 204

    STACK_OFFSET = 22

    COLUMN_SPACING = 8
    ROW_SPACING = 16

    PADDING_X = 28
    PADDING_TOP = 110
    PADDING_BOTTOM = 30

    SIDEBOARD_GAP = 36

    MAIN_COLUMNS = 6
    SIDEBOARD_COLUMNS = 2

    SECTION_GAP = 30
    SECTION_LABEL_HEIGHT = 22

    BG_TOP = (18, 20, 30)
    BG_BOTTOM = (8, 8, 14)

    HEADER_BG = (10, 12, 20, 220)

    TEXT_PRIMARY = (230, 230, 235)
    TEXT_SECONDARY = (160, 160, 175)
    TEXT_SECTION = (200, 165, 70)
    TEXT_SHADOW = (0, 0, 0)

    DIVIDER_COLOR = (60, 65, 85)
    SECTION_LINE_COLOR = (80, 75, 55)
    CARD_SHADOW = (0, 0, 0, 160)
    CARD_BORDER = (45, 45, 58)
    CARD_GLOW = (70, 70, 90)

    SIDEBOARD_DIVIDER = (55, 60, 80)

    TITLE_FONT_SIZE = 42
    SUBTITLE_FONT_SIZE = 18
    SECTION_FONT_SIZE = 15
    LABEL_FONT_SIZE = 13

    @classmethod
    def _try_fonts(cls, size):
        """Prova vari font, fallback al default."""
        for name in [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "arialbd.ttf",
            "arial.ttf",
            "DejaVuSans-Bold.ttf",
        ]:
            try:
                return ImageFont.truetype(name, size)
            except Exception:
                continue
        return ImageFont.load_default()

    @classmethod
    def _try_font_regular(cls, size):
        for name in [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "arial.ttf",
            "DejaVuSans.ttf",
        ]:
            try:
                return ImageFont.truetype(name, size)
            except Exception:
                continue
        return ImageFont.load_default()

    @classmethod
    async def download_card_image(cls, session: aiohttp.ClientSession, url: str):
        try:
            async with session.get(url) as response:
                if response.status != 200:
                    return None
                data = await response.read()
                img = Image.open(BytesIO(data)).convert("RGBA")
                img = img.resize((cls.CARD_WIDTH, cls.CARD_HEIGHT), Image.LANCZOS)
                return img
        except Exception:
            return None
    
    @classmethod
    def _get_background_path(cls, mainboard: list):
        """Determina il percorso dell'immagine di sfondo in base ai colori del mazzo."""
        color_counts = {
            "red": 0,    # Mountain / Great Furnace
            "blue": 0,   # Island / Seat of the Synod
            "black": 0,  # Swamp / Vault of Whispers
            "white": 0,  # Plains / Ancient Den
            "green": 0,  # Forest / Tree of Tales
        }

        land_mapping = {
            "Mountain": "red", "Great Furnace": "red",
            "Island": "blue", "Seat of the Synod": "blue",
            "Swamp": "black", "Vault of Whispers": "black",
            "Plains": "white", "Ancient Den": "white",
            "Forest": "green", "Tree of Tales": "green",
            "Darksteel Citadel": None
        }

        for card in mainboard:
            type_line = card.get("type_line", "")
            if "Land" in type_line:
                name = card.get("name")
                qty = card.get("quantity", 1)

                if name in land_mapping:
                    color_key = land_mapping[name]
                    if color_key:
                        color_counts[color_key] += qty
                
                else:
                    colors = card.get("colors", [])
                    if "R" in colors: color_counts["red"] += qty
                    if "U" in colors: color_counts["blue"] += qty
                    if "B" in colors: color_counts["black"] += qty
                    if "W" in colors: color_counts["white"] += qty
                    if "G" in colors: color_counts["green"] += qty

        dominant_color = max(color_counts, key=color_counts.get)
        
        if color_counts[dominant_color] == 0:
            return "assets/backgrounds/default.png"

        R = color_counts["red"]
        U = color_counts["blue"]
        B = color_counts["black"]
        W = color_counts["white"]
        G = color_counts["green"]

        if R > 0 and U > 0 and G > 0:
            return "assets/backgrounds/temur.png"

        if R > 0 and W > 0 and B > 0:
            return "assets/backgrounds/mardu.png"

        if G > 0 and W > 0 and U > 0:
            return "assets/backgrounds/bant.png"

        if B > 0 and G > 0 and U > 0:
            return "assets/backgrounds/sultai.png"

        if R > 0 and U > 0 and B > 0:
            return "assets/backgrounds/grixis.png"

        if R > 0 and G > 0 and W > 0:
            return "assets/backgrounds/naya.png"

        if R > 0 and W > 0 and U > 0:
            return "assets/backgrounds/jeskai.png"

        if G > 0 and B > 0 and W > 0:
            return "assets/backgrounds/abzan.png"

        if B > 0 and R > 0 and G > 0:
            return "assets/backgrounds/jund.png"

        if W > 0 and U > 0 and B > 0:
            return "assets/backgrounds/esper.png"

        # Guilds (2-color combinations)
        if W > 0 and U > 0:
            return "assets/backgrounds/azorius.png"

        if U > 0 and B > 0:
            return "assets/backgrounds/dimir.png"

        if B > 0 and R > 0:
            return "assets/backgrounds/rakdos.png"

        if R > 0 and G > 0:
            return "assets/backgrounds/gruul.png"

        if G > 0 and W > 0:
            return "assets/backgrounds/selesnya.png"

        if W > 0 and B > 0:
            return "assets/backgrounds/orzhov.png"

        if U > 0 and R > 0:
            return "assets/backgrounds/izzet.png"

        if B > 0 and G > 0:
            return "assets/backgrounds/golgari.png"

        if R > 0 and W > 0:
            return "assets/backgrounds/boros.png"

        if G > 0 and U > 0:
            return "assets/backgrounds/simic.png"

        paths = {
            "red": "assets/backgrounds/red.png",
            "blue": "assets/backgrounds/blue.png",
            "black": "assets/backgrounds/black.png",
            "white": "assets/backgrounds/white.png",
            "green": "assets/backgrounds/green.png"
        }

        return paths.get(dominant_color, "assets/backgrounds/default.png")
    # ──────────────────────────────────────────────────────────────────
    # LOGO WATERMARK
    # ──────────────────────────────────────────────────────────────────

    LOGO_PATH = "assets/logo_clepshydra.png"

    LOGO_SIZE = 180

    LOGO_ALPHA = 80

    LOGO_MARGIN = 18

    @classmethod
    def _extract_dominant_color(cls, image: Image.Image) -> tuple[int, int, int]:
        """
        Restituisce il colore medio (R, G, B) dell'immagine passata,
        ignorando pixel quasi-neri (< soglia 30 su tutti i canali)
        che porterebbero il risultato verso il nero e nasconderebbero
        il logo sullo sfondo scurito.
        """
        # Lavora su una miniatura per velocità
        thumb = image.convert("RGB").resize((64, 64), Image.LANCZOS)
        pixels = list(thumb.getdata())

        r_sum = g_sum = b_sum = count = 0
        for r, g, b in pixels:
            if r < 30 and g < 30 and b < 30:
                continue
            r_sum += r
            g_sum += g
            b_sum += b
            count += 1

        if count == 0:
            return (128, 0, 200)

        return (r_sum // count, g_sum // count, b_sum // count)

    @classmethod
    def _apply_logo_watermark(
        cls,
        canvas: Image.Image,
        bg_image: Image.Image,
        center_x: int | None = None,
    ) -> None:
        """
        Carica il logo di Clepshydra, lo colora con il colore dominante
        dello sfondo (pre-oscuramento) e lo incolla come watermark
        semitrasparente in basso al canvas.

        Posizionamento orizzontale:
        - Se center_x è fornito, il logo viene centrato su quella coordinata X.
        - Altrimenti viene centrato sull'intero canvas.

        Verticalmente è sempre ancorato al bordo inferiore con LOGO_MARGIN.

        Modifica `canvas` in-place.
        """
        try:
            logo_src = Image.open(cls.LOGO_PATH).convert("RGBA")
        except Exception:
            return

        lw, lh = logo_src.size
        ratio = cls.LOGO_SIZE / max(lw, lh)
        new_lw = int(lw * ratio)
        new_lh = int(lh * ratio)
        logo_src = logo_src.resize((new_lw, new_lh), Image.LANCZOS)
        
        dom_r, dom_g, dom_b = cls._extract_dominant_color(bg_image)
        r_ch, g_ch, b_ch, a_ch = logo_src.split()
        a_scaled = a_ch.point(lambda v: int(v * cls.LOGO_ALPHA / 255))

        colored_logo = Image.new("RGBA", (new_lw, new_lh), (dom_r, dom_g, dom_b, 0))
        colored_logo.putalpha(a_scaled)

        canvas_w, canvas_h = canvas.size

        cx = center_x if center_x is not None else canvas_w // 2
        pos_x = cx - new_lw // 2

        pos_y = canvas_h - new_lh - cls.LOGO_MARGIN

        canvas.alpha_composite(colored_logo, (pos_x, pos_y))

    @classmethod
    def draw_gradient_background(cls, canvas):
        draw = ImageDraw.Draw(canvas)
        width, height = canvas.size
        for y in range(height):
            ratio = y / height
            r = int(cls.BG_TOP[0] * (1 - ratio) + cls.BG_BOTTOM[0] * ratio)
            g = int(cls.BG_TOP[1] * (1 - ratio) + cls.BG_BOTTOM[1] * ratio)
            b = int(cls.BG_TOP[2] * (1 - ratio) + cls.BG_BOTTOM[2] * ratio)
            draw.line([(0, y), (width, y)], fill=(r, g, b))

    @classmethod
    def sort_mainboard(cls, mainboard: list):
        creatures, spells, lands = [], [], []
        for card in mainboard:
            type_line = card.get("type_line", "")
            if "Land" in type_line:
                is_basic = card["name"] in ["Mountain", "Island", "Swamp", "Plains", "Forest"] or "Basic Land" in type_line
                
                if is_basic:
                    qty = card.get("quantity", 1)
                    while qty > 0:
                        take = min(qty, 4)
                        new_card = card.copy()
                        new_card["quantity"] = take
                        lands.append(new_card)
                        qty -= take
                else:
                    lands.append(card)
            elif "Creature" in type_line:
                creatures.append(card)
            else:
                spells.append(card)
        creatures.sort(key=lambda c: (c.get("cmc", 0), c["name"]))
        spells.sort(key=lambda c: (c.get("cmc", 0), c["name"]))
        lands.sort(key=lambda c: c["name"])
        return creatures, spells, lands

    @classmethod
    def calc_stack_height(cls, quantity: int) -> int:
        return cls.CARD_HEIGHT + (quantity - 1) * cls.STACK_OFFSET

    @classmethod
    def layout_section(cls, cards: list, start_col: int, columns: int):
        """
        Restituisce lista di (card, col, row) per una sezione.
        Riempie per colonne (non per righe).
        """
        result = []
        col = start_col
        row = 0
        for card in cards:
            result.append((card, col, row))
            col += 1
            if col >= start_col + columns:
                col = start_col
                row += 1
        return result

    @classmethod
    def draw_card_stack(cls, canvas, draw, card, x, y):
        """Disegna lo stack di copie di una carta."""
        qty = card.get("quantity", 1)
        img = card.get("image")

        for i in range(qty):
            offset_y = y + i * cls.STACK_OFFSET

            sx, sy = x + 3, offset_y + 3
            shadow_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            shadow_draw = ImageDraw.Draw(shadow_layer)
            shadow_draw.rounded_rectangle(
                [sx, sy, sx + cls.CARD_WIDTH, sy + cls.CARD_HEIGHT],
                radius=4,
                fill=(0, 0, 0, 130)
            )
            canvas.alpha_composite(shadow_layer)

            glow_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            glow_draw = ImageDraw.Draw(glow_layer)
            glow_draw.rounded_rectangle(
                [x - 2, offset_y - 2, x + cls.CARD_WIDTH + 2, offset_y + cls.CARD_HEIGHT + 2],
                radius=5,
                fill=(0, 0, 0, 0),
                outline=(*cls.CARD_GLOW, 80),
                width=2
            )
            canvas.alpha_composite(glow_layer)

            if img:
                card_layer = Image.new("RGBA", (cls.CARD_WIDTH, cls.CARD_HEIGHT), (0, 0, 0, 0))
                mask = Image.new("L", (cls.CARD_WIDTH, cls.CARD_HEIGHT), 0)
                mask_draw = ImageDraw.Draw(mask)
                mask_draw.rounded_rectangle([0, 0, cls.CARD_WIDTH, cls.CARD_HEIGHT], radius=4, fill=255)
                card_layer.paste(img.convert("RGBA"), (0, 0))
                card_layer.putalpha(mask)
                canvas.alpha_composite(card_layer, (x, offset_y))
            else:
                placeholder = Image.new("RGBA", (cls.CARD_WIDTH, cls.CARD_HEIGHT), (35, 35, 50, 255))
                canvas.alpha_composite(placeholder, (x, offset_y))

            border_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            border_draw = ImageDraw.Draw(border_layer)
            border_draw.rounded_rectangle(
                [x, offset_y, x + cls.CARD_WIDTH, offset_y + cls.CARD_HEIGHT],
                radius=4,
                fill=(0, 0, 0, 0),
                outline=(*cls.CARD_BORDER, 200),
                width=1
            )
            canvas.alpha_composite(border_layer)

    @classmethod
    def draw_section_label(cls, draw, x, y, label: str, count: int, font, label_font):
        """Disegna etichetta sezione (es: 'Creature — 20')."""
        text = f"{label}  ·  {count}"
        # Shadow
        draw.text((x + 1, y + 1), text, fill=(0, 0, 0, 200), font=font)
        draw.text((x, y), text, fill=cls.TEXT_SECTION, font=font)

    @classmethod
    async def create_deck_showcase(
        cls,
        session: aiohttp.ClientSession,
        mainboard: list,
        sideboard: list,
        player_name: str = None,
        deck_name: str = "ARTISAN DECK",
    ):
        # ──────────────────────────────────────────────────
        # DOWNLOAD IMMAGINI
        # ──────────────────────────────────────────────────
        all_cards = mainboard + sideboard
        for card in all_cards:
            card["image"] = await cls.download_card_image(session, card["image_url"])

        # ──────────────────────────────────────────────────
        # SORT MAINBOARD IN SEZIONI
        # ──────────────────────────────────────────────────
        creatures, spells, lands = cls.sort_mainboard(mainboard)
        sections = [
            ("Creature", creatures),
            ("Spell", spells),
            ("Land", lands),
        ]
        sections = [(label, cards) for label, cards in sections if cards]

        # ──────────────────────────────────────────────────
        # CALCOLA LAYOUT MAINBOARD
        # ──────────────────────────────────────────────────
        col_width = cls.CARD_WIDTH + cls.COLUMN_SPACING

        section_layouts = []
        for label, cards in sections:
            max_qty = max((c["quantity"] for c in cards), default=1)
            max_stack_h = cls.calc_stack_height(max_qty)
            rows = math.ceil(len(cards) / cls.MAIN_COLUMNS)
            section_height = (
                cls.SECTION_LABEL_HEIGHT
                + 6
                + rows * max_stack_h
                + (rows - 1) * cls.ROW_SPACING
            )
            section_layouts.append({
                "label": label,
                "cards": cards,
                "max_stack_h": max_stack_h,
                "rows": rows,
                "section_height": section_height,
            })

        main_content_height = sum(s["section_height"] for s in section_layouts)
        main_content_height += cls.SECTION_GAP * (len(section_layouts) - 1)

        main_width = cls.MAIN_COLUMNS * col_width - cls.COLUMN_SPACING

        # ──────────────────────────────────────────────────
        # CALCOLA LAYOUT SIDEBOARD
        # ──────────────────────────────────────────────────
        side_col_width = cls.CARD_WIDTH + cls.COLUMN_SPACING
        side_rows = math.ceil(len(sideboard) / cls.SIDEBOARD_COLUMNS)

        side_max_qty = max((c["quantity"] for c in sideboard), default=1)
        side_stack_h = cls.calc_stack_height(side_max_qty)
        side_content_height = (
            side_rows * side_stack_h
            + (side_rows - 1) * cls.ROW_SPACING
        )

        side_width = cls.SIDEBOARD_COLUMNS * side_col_width - cls.COLUMN_SPACING

        # ──────────────────────────────────────────────────
        # CANVAS SIZE
        # ──────────────────────────────────────────────────
        content_height = max(main_content_height, side_content_height)
        canvas_width = (cls.PADDING_X + main_width + cls.SIDEBOARD_GAP + side_width + cls.PADDING_X)
        canvas_height = (cls.PADDING_TOP + content_height + cls.PADDING_BOTTOM)

        bg_path = cls._get_background_path(mainboard)
        
        # bg_for_logo: riferimento allo sfondo ritagliato PRIMA dell'oscuramento,
        # usato da _apply_logo_watermark per campionare il colore dominante reale.
        bg_for_logo = None

        try:
            bg_image = Image.open(bg_path).convert("RGBA")
            bg_w, bg_h = bg_image.size

            scale = max(canvas_width / bg_w, canvas_height / bg_h)
            new_size = (int(bg_w * scale), int(bg_h * scale))

            bg_resized = bg_image.resize(new_size, Image.LANCZOS)

            offset_x = (new_size[0] - canvas_width) // 2
            offset_y = (new_size[1] - canvas_height) // 2
            canvas = bg_resized.crop((
                offset_x,
                offset_y,
                offset_x + canvas_width,
                offset_y + canvas_height
            ))

            bg_for_logo = canvas.copy()

            enhancer = ImageEnhance.Brightness(canvas)
            canvas = enhancer.enhance(0.4)
        except Exception:
            canvas = Image.new("RGBA", (canvas_width, canvas_height), cls.BG_TOP)
            cls.draw_gradient_background(canvas)

        # ──────────────────────────────────────────────────
        # LOGO WATERMARK
        # ──────────────────────────────────────────────────
        # div_x è il divisore verticale main/side → calcolato con la stessa
        _div_x = cls.PADDING_X + main_width + cls.SIDEBOARD_GAP // 2
        _sideboard_center_x = (_div_x + canvas_width) // 2

        cls._apply_logo_watermark(
            canvas,
            bg_for_logo if bg_for_logo is not None else canvas,
            center_x=_sideboard_center_x,
        )

        draw = ImageDraw.Draw(canvas)

        # ──────────────────────────────────────────────────
        # FONTS
        # ──────────────────────────────────────────────────
        font_title = cls._try_fonts(cls.TITLE_FONT_SIZE)
        font_subtitle = cls._try_font_regular(cls.SUBTITLE_FONT_SIZE)
        font_section = cls._try_fonts(cls.SECTION_FONT_SIZE)
        font_label = cls._try_font_regular(cls.LABEL_FONT_SIZE)

        # ──────────────────────────────────────────────────
        # HEADER
        # ──────────────────────────────────────────────────
        header_layer = Image.new("RGBA", (canvas_width, cls.PADDING_TOP), (0, 0, 0, 0))
        header_draw = ImageDraw.Draw(header_layer)
        header_draw.rectangle(
            [0, 0, canvas_width, cls.PADDING_TOP],
            fill=(12, 14, 22, 200)
        )
        canvas.alpha_composite(header_layer)

        title_y = 18
        draw.text((cls.PADDING_X + 2, title_y + 2), deck_name, fill=(0, 0, 0, 200), font=font_title)
        draw.text((cls.PADDING_X, title_y), deck_name, fill=cls.TEXT_PRIMARY, font=font_title)

        if player_name:
            sub_y = title_y + cls.TITLE_FONT_SIZE + 4
            subtitle_text = f"by {player_name}"
            draw.text((cls.PADDING_X + 1, sub_y + 1), subtitle_text, fill=(0, 0, 0, 180), font=font_subtitle)
            draw.text((cls.PADDING_X, sub_y), subtitle_text, fill=cls.TEXT_SECONDARY, font=font_subtitle)

        side_x = cls.PADDING_X + main_width + cls.SIDEBOARD_GAP
        draw.text((side_x + 1, title_y + 1), "SIDEBOARD", fill=(0, 0, 0, 200), font=font_title)
        draw.text((side_x, title_y), "SIDEBOARD", fill=cls.TEXT_PRIMARY, font=font_title)

        line_y = cls.PADDING_TOP - 2
        draw.line(
            [(cls.PADDING_X, line_y), (cls.PADDING_X + main_width, line_y)],
            fill=cls.DIVIDER_COLOR,
            width=1
        )

        # ──────────────────────────────────────────────────
        # DIVIDER VERTICALE MAIN / SIDE
        # ──────────────────────────────────────────────────
        div_x = cls.PADDING_X + main_width + cls.SIDEBOARD_GAP // 2
        draw.line(
            [(div_x, 10), (div_x, canvas_height - 10)],
            fill=cls.SIDEBOARD_DIVIDER,
            width=1
        )

        # ──────────────────────────────────────────────────
        # MAINBOARD: RENDER PER SEZIONE
        # ──────────────────────────────────────────────────
        current_y = cls.PADDING_TOP + 8
        main_x = cls.PADDING_X

        for sec_idx, sec in enumerate(section_layouts):
            label = sec["label"]
            cards = sec["cards"]
            max_stack_h = sec["max_stack_h"]
            total_in_section = sum(c["quantity"] for c in cards)

            # Label sezione
            cls.draw_section_label(draw, main_x, current_y, label, total_in_section, font_section, font_label)
            current_y += cls.SECTION_LABEL_HEIGHT + 6

            draw.line(
                [(main_x, current_y - 2), (main_x + main_width, current_y - 2)],
                fill=cls.SECTION_LINE_COLOR,
                width=1
            )

            for card_idx, card in enumerate(cards):
                col = card_idx % cls.MAIN_COLUMNS
                row = card_idx // cls.MAIN_COLUMNS

                x = main_x + col * col_width
                y = current_y + row * (max_stack_h + cls.ROW_SPACING)

                cls.draw_card_stack(canvas, draw, card, x, y)

            rows = math.ceil(len(cards) / cls.MAIN_COLUMNS)
            current_y += rows * (max_stack_h + cls.ROW_SPACING) - cls.ROW_SPACING

            if sec_idx < len(section_layouts) - 1:
                current_y += cls.SECTION_GAP

        # ──────────────────────────────────────────────────
        # SIDEBOARD: RENDER
        # ──────────────────────────────────────────────────
        side_y = cls.PADDING_TOP + 8

        # Label count
        side_total = sum(c["quantity"] for c in sideboard)
        draw.text(
            (side_x + 1, side_y - cls.SECTION_LABEL_HEIGHT - 4 + 1),
            f"({side_total} carte)",
            fill=(0, 0, 0, 180),
            font=font_label
        )
        draw.text(
            (side_x, side_y - cls.SECTION_LABEL_HEIGHT - 4),
            f"({side_total} carte)",
            fill=cls.TEXT_SECONDARY,
            font=font_label
        )

        for card_idx, card in enumerate(sideboard):
            col = card_idx % cls.SIDEBOARD_COLUMNS
            row = card_idx // cls.SIDEBOARD_COLUMNS

            x = side_x + col * side_col_width
            y = side_y + row * (side_stack_h + cls.ROW_SPACING)

            cls.draw_card_stack(canvas, draw, card, x, y)

        # ──────────────────────────────────────────────────
        # EXPORT
        # ──────────────────────────────────────────────────
        output = BytesIO()
        canvas_rgb = canvas.convert("RGB")
        canvas_rgb.save(output, format="PNG", optimize=True)
        output.seek(0)
        return output