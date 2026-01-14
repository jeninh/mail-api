import pytest
from app.rubber_stamp_formatter import format_rubber_stamps, format_for_slack_display


class TestFormatRubberStamps:
    def test_short_line_unchanged(self):
        text = "Hack Club"
        result = format_rubber_stamps(text)
        assert result == "Hack Club"

    def test_respects_existing_newlines(self):
        text = "Hack Club\nStickers"
        result = format_rubber_stamps(text)
        assert result == "Hack Club\nStickers"

    def test_splits_long_line_on_word_boundary(self):
        text = "Haxmas 2024 Winner"
        result = format_rubber_stamps(text)
        assert "Haxmas 2024" in result
        assert "Winner" in result

    def test_force_splits_long_word(self):
        text = "Congratulations"
        result = format_rubber_stamps(text, max_line_length=11)
        lines = result.split('\n')
        assert len(lines) == 2
        assert lines[0] == "Congratulat"
        assert lines[1] == "ions"

    def test_complex_example(self):
        text = "1x pack of stickers\n1x Postcard of Euan eating a Bread"
        result = format_rubber_stamps(text)
        lines = result.split('\n')
        for line in lines:
            assert len(line) <= 11

    def test_empty_string(self):
        result = format_rubber_stamps("")
        assert result == ""

    def test_strips_whitespace(self):
        text = "  Hello  \n  World  "
        result = format_rubber_stamps(text)
        assert "  " not in result

    def test_mixed_content(self):
        text = "3x Stickers\n1x T-Shirt Large"
        result = format_rubber_stamps(text)
        lines = result.split('\n')
        assert lines[0] == "3x Stickers"
        assert all(len(line) <= 11 for line in lines)


class TestFormatForSlackDisplay:
    def test_adds_bullet_points(self):
        text = "Stickers\nPostcard"
        result = format_for_slack_display(text)
        assert result == "  > Stickers\n  > Postcard"

    def test_empty_string(self):
        result = format_for_slack_display("")
        assert result == ""

    def test_single_item(self):
        text = "Prize Package"
        result = format_for_slack_display(text)
        assert result == "  > Prize Package"

    def test_handles_blank_lines(self):
        text = "Item 1\n\nItem 2"
        result = format_for_slack_display(text)
        assert result == "  > Item 1\n  > Item 2"
