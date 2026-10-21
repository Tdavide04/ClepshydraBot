import json

import core.json_state as json_state


class TestLoadJsonState:
    def test_returns_a_copy_of_default_when_file_missing(self, tmp_path):
        default = {"latest_url": None, "latest_lastmod": None}
        path = str(tmp_path / "state.json")

        result = json_state.load_json_state(path, default)

        assert result == default
        assert result is not default, "must not return the same default object (mutable and shared)"

    def test_loads_existing_file_content(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text(
            json.dumps({"latest_url": "https://x", "latest_lastmod": "2026-01-01"}), encoding="utf-8"
        )

        result = json_state.load_json_state(str(path), {})

        assert result == {"latest_url": "https://x", "latest_lastmod": "2026-01-01"}


class TestSaveJsonState:
    def test_writes_a_file_that_can_be_reloaded(self, tmp_path):
        path = str(tmp_path / "state.json")

        json_state.save_json_state(path, {"latest_url": "https://x"})

        assert json_state.load_json_state(path, {}) == {"latest_url": "https://x"}

    def test_creates_missing_parent_directories(self, tmp_path):
        path = str(tmp_path / "nested" / "dir" / "state.json")

        json_state.save_json_state(path, {"a": 1})

        assert json_state.load_json_state(path, {}) == {"a": 1}

    def test_overwrites_an_existing_file(self, tmp_path):
        path = str(tmp_path / "state.json")

        json_state.save_json_state(path, {"a": 1})
        json_state.save_json_state(path, {"a": 2})

        assert json_state.load_json_state(path, {}) == {"a": 2}

    def test_does_not_leave_the_tmp_file_behind(self, tmp_path):
        path = tmp_path / "state.json"

        json_state.save_json_state(str(path), {"a": 1})

        assert not (tmp_path / "state.json.tmp").exists()
