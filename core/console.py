from datetime import datetime


def log(message: str) -> None:
    """Console print() with a timestamp, in the same format as discord.py's
    logs ('[2026-10-12 15:20:04]') - without it, `pm2 logs` gave no way to
    tell WHEN an event happened (observed 2026-10-12: it was impossible to
    establish whether the Banned and Restricted check ran before the new
    announcement appeared in the sitemap). Born in features/monitors/sitemap.py,
    moved here once it was needed outside the sitemap monitors too."""

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")
