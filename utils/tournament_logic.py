OMW_FILLED = "█"
OMW_EMPTY = "░"
OMW_LENGTH = 10

RANK_EMOJIS = {1: "🥇", 2: "🥈", 3: "🥉"}


def rank_label(position: int) -> str:
    return RANK_EMOJIS.get(position, f"{position}.")


def omw_bar(pct: float) -> str:
    filled = round(pct / 10)
    filled = max(0, min(10, filled))
    empty = 10 - filled
    return OMW_FILLED * filled + OMW_EMPTY * empty + f" {pct:.1f}%"


def split_into_columns(items: list) -> tuple[list, list]:
    mid = (len(items) + 1) // 2
    return items[:mid], items[mid:]


def split_field_value(lines: list[str], max_chars: int = 1000) -> list[str]:
    chunks = []
    current = []
    current_len = 0
    for line in lines:
        line_len = len(line)
        if current and current_len + line_len + 1 > max_chars:
            chunks.append("\n".join(current))
            current = [line]
            current_len = line_len
        else:
            current.append(line)
            current_len += line_len + 1
    if current:
        chunks.append("\n".join(current))
    return chunks
