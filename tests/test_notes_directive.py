"""Unit tests for the per-note synthesis directive parser.

Pure-function tests — no network, no DB. Covers front matter (single-line and
block scalar), the @prompt first-line form, precedence, "none", and malformed
front matter.
"""
import unittest

from services.notes_service import extract_synthesis_directive


class ExtractSynthesisDirectiveTest(unittest.TestCase):
    def test_none_when_plain_note(self):
        self.assertIsNone(extract_synthesis_directive("Just a normal note about Q1 earnings."))
        self.assertIsNone(extract_synthesis_directive(""))
        self.assertIsNone(extract_synthesis_directive(None))

    def test_at_prompt_first_line(self):
        text = "@prompt: Extract only segment YoY growth\nRest of the note body here."
        self.assertEqual(
            extract_synthesis_directive(text), "Extract only segment YoY growth"
        )

    def test_at_prompt_after_leading_blank_lines(self):
        text = "\n\n   @prompt: Focus on catalysts  \nbody"
        self.assertEqual(extract_synthesis_directive(text), "Focus on catalysts")

    def test_at_prompt_not_first_line_is_ignored(self):
        text = "Some intro line\n@prompt: too late"
        self.assertIsNone(extract_synthesis_directive(text))

    def test_front_matter_single_line(self):
        text = "---\nprompt: Summarize risks only\n---\nBody of the note."
        self.assertEqual(extract_synthesis_directive(text), "Summarize risks only")

    def test_front_matter_quoted_value(self):
        text = '---\nprompt: "Quoted directive"\n---\nbody'
        self.assertEqual(extract_synthesis_directive(text), "Quoted directive")

    def test_front_matter_block_scalar(self):
        text = (
            "---\n"
            "prompt: |\n"
            "  Line one of directive\n"
            "  Line two of directive\n"
            "---\n"
            "Note body."
        )
        self.assertEqual(
            extract_synthesis_directive(text),
            "Line one of directive\nLine two of directive",
        )

    def test_front_matter_wins_over_at_prompt(self):
        # @prompt can't actually be the first line if front matter is present, but
        # the front-matter branch must take precedence regardless.
        text = "---\nprompt: front matter wins\n---\n@prompt: should be ignored"
        self.assertEqual(extract_synthesis_directive(text), "front matter wins")

    def test_malformed_front_matter_no_closing_fence(self):
        text = "---\nprompt: never closed\nsome more text without a fence"
        self.assertIsNone(extract_synthesis_directive(text))

    def test_front_matter_without_prompt_key_is_none(self):
        text = "---\ntitle: hello\ntags: a, b\n---\nbody"
        self.assertIsNone(extract_synthesis_directive(text))


if __name__ == "__main__":
    unittest.main()
