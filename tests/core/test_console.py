import re

import core.console as console


class TestLog:
    def test_prefixes_the_message_with_a_timestamp(self, capsys):
        console.log("[BAN ANNOUNCEMENT] no change")
        out = capsys.readouterr().out.strip()
        assert re.fullmatch(r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] \[BAN ANNOUNCEMENT\] no change", out)
