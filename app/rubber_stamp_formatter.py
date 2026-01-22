def format_rubber_stamps(text: str, max_line_length: int = 11) -> str:
    """
    Formats rubber stamps text to fit physical rubber stamp constraints.

    The rubber_stamps field should contain items to pack. For example:
    - "1x pack of stickers\\n1x Postcard of Euan eating a Bread"
    - "3x Hack Club stickers\\n1x Thank you card"

    Rules:
    1. Respects existing \\n line breaks
    2. Splits any line longer than max_line_length characters
    3. Splits on word boundaries when possible
    4. Force-splits words longer than max_line_length

    Args:
        text: The raw rubber stamps text
        max_line_length: Maximum characters per line (default: 11)

    Returns:
        Formatted text with proper line breaks

    Example:
        Input: "Hack Club\\nHaxmas 2024 Winner Congratulations"
        Output: "Hack Club\\nHaxmas 2024\\nWinner\\nCongratula\\ntions"
    """
    if not text:
        return ""

    lines = text.split('\n')
    formatted_lines = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if len(line) <= max_line_length:
            formatted_lines.append(line)
            continue

        words = line.split()
        current_line = ""

        for word in words:
            if len(word) > max_line_length:
                if current_line:
                    formatted_lines.append(current_line)
                    current_line = ""

                for i in range(0, len(word), max_line_length):
                    formatted_lines.append(word[i:i + max_line_length])
                continue

            test_line = word if not current_line else f"{current_line} {word}"

            if len(test_line) <= max_line_length:
                current_line = test_line
            else:
                formatted_lines.append(current_line)
                current_line = word

        if current_line:
            formatted_lines.append(current_line)

    return '\n'.join(formatted_lines)


def format_for_slack_display(text: str) -> str:
    """
    Formats rubber stamps for Slack message display.
    Adds proper indentation and bullet points.

    Args:
        text: The raw rubber stamps text

    Returns:
        Formatted text for Slack display
    """
    if not text:
        return ""

    lines = text.split('\n')
    formatted_lines = []

    for line in lines:
        line = line.strip()
        if line:
            formatted_lines.append(f"  > {line}")

    return '\n'.join(formatted_lines)
