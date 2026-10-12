from datetime import datetime


def log(message: str) -> None:
    """print() su console con timestamp, nello stesso formato dei log di
    discord.py ('[2026-10-12 15:20:04]') - senza, in `pm2 logs` era
    impossibile capire QUANDO un evento fosse avvenuto (osservato il
    2026-10-12: non si poteva stabilire se il check del Banned and Restricted
    avesse preceduto la comparsa del nuovo annuncio sul sitemap). Nata in
    utils/sitemap_monitor.py, spostata qui quando e' servita anche fuori dai
    monitor sitemap."""

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")
