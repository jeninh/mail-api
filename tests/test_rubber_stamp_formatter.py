
from app.rubber_stamp_formatter import format_for_slack_display, format_rubber_stamps


class TestFormatRubberStampsBasic:
    def test_empty_string(self):
        assert format_rubber_stamps("") == ""

    def test_none_like_empty(self):
        assert format_rubber_stamps("") == ""

    def test_short_single_line(self):
        assert format_rubber_stamps("Hack Club") == "Hack Club"

    def test_exact_max_length(self):
        assert format_rubber_stamps("12345678901") == "12345678901"

    def test_whitespace_only(self):
        assert format_rubber_stamps("   ") == ""

    def test_strips_leading_trailing_whitespace(self):
        assert format_rubber_stamps("  Hack Club  ") == "Hack Club"


class TestFormatRubberStampsMultipleLines:
    def test_respects_existing_newlines(self):
        result = format_rubber_stamps("Line 1\nLine 2")
        assert result == "Line 1\nLine 2"

    def test_empty_lines_removed(self):
        result = format_rubber_stamps("Line 1\n\nLine 2")
        assert result == "Line 1\nLine 2"

    def test_multiple_newlines(self):
        result = format_rubber_stamps("A\nB\nC")
        assert result == "A\nB\nC"


class TestFormatRubberStampsWordWrapping:
    def test_splits_long_line_on_word_boundary(self):
        result = format_rubber_stamps("Haxmas 2024 Winner")
        assert result == "Haxmas 2024\nWinner"

    def test_multiple_words_fit_on_line(self):
        result = format_rubber_stamps("Hi there")
        assert result == "Hi there"

    def test_words_accumulate_until_max(self):
        result = format_rubber_stamps("A B C D E F")
        lines = result.split('\n')
        for line in lines:
            assert len(line) <= 11

    def test_docstring_example(self):
        result = format_rubber_stamps("Hack Club\nHaxmas 2024 Winner Congratulations")
        assert "Hack Club" in result
        assert "Haxmas 2024" in result
        assert "Winner" in result


class TestFormatRubberStampsForceSplit:
    def test_force_splits_long_word(self):
        result = format_rubber_stamps("Congratulations")
        assert result == "Congratulat\nions"

    def test_very_long_word_multiple_splits(self):
        result = format_rubber_stamps("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        lines = result.split('\n')
        assert lines[0] == "ABCDEFGHIJK"
        assert lines[1] == "LMNOPQRSTUV"
        assert lines[2] == "WXYZ"

    def test_long_word_after_short_words(self):
        result = format_rubber_stamps("Hi Congratulations")
        lines = result.split('\n')
        assert lines[0] == "Hi"
        assert lines[1] == "Congratulat"
        assert lines[2] == "ions"


class TestFormatRubberStampsCustomMaxLength:
    def test_custom_max_length(self):
        result = format_rubber_stamps("Hello World", max_line_length=5)
        assert result == "Hello\nWorld"

    def test_larger_max_length(self):
        result = format_rubber_stamps("Hello World Everyone", max_line_length=20)
        assert result == "Hello World Everyone"

    def test_max_length_one(self):
        result = format_rubber_stamps("AB", max_line_length=1)
        assert result == "A\nB"


class TestFormatRubberStampsEdgeCases:
    def test_single_character(self):
        assert format_rubber_stamps("X") == "X"

    def test_typical_rubber_stamp_content(self):
        text = "1x pack of stickers\n1x Postcard"
        result = format_rubber_stamps(text)
        lines = result.split('\n')
        for line in lines:
            assert len(line) <= 11

    def test_preserves_numbers_and_special_chars(self):
        result = format_rubber_stamps("3x Stickers")
        assert result == "3x Stickers"

    def test_mixed_content(self):
        text = "Hi\nCongratulations\nBye"
        result = format_rubber_stamps(text)
        assert "Hi" in result
        assert "Bye" in result


class TestFormatForSlackDisplayBasic:
    def test_empty_string(self):
        assert format_for_slack_display("") == ""

    def test_single_line(self):
        assert format_for_slack_display("Hello") == "  > Hello"

    def test_strips_whitespace(self):
        assert format_for_slack_display("  Hello  ") == "  > Hello"


class TestFormatForSlackDisplayMultipleLines:
    def test_multiple_lines(self):
        result = format_for_slack_display("Line 1\nLine 2")
        assert result == "  > Line 1\n  > Line 2"

    def test_empty_lines_removed(self):
        result = format_for_slack_display("Line 1\n\nLine 2")
        assert result == "  > Line 1\n  > Line 2"

    def test_whitespace_only_lines_removed(self):
        result = format_for_slack_display("Line 1\n   \nLine 2")
        assert result == "  > Line 1\n  > Line 2"


class TestFormatForSlackDisplayFormatting:
    def test_bullet_point_format(self):
        result = format_for_slack_display("Test")
        assert result.startswith("  > ")

    def test_multiple_items(self):
        text = "1x Stickers\n1x Postcard\n1x Thank you"
        result = format_for_slack_display(text)
        lines = result.split('\n')
        assert len(lines) == 3
        for line in lines:
            assert line.startswith("  > ")
