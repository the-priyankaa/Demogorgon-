import unittest

from stdedit.languages.schema import detect_language, tokenize


class TestLanguageDetection(unittest.TestCase):
    def test_detects_python_by_extension(self):
        self.assertEqual(detect_language("main.py"), "python")
        self.assertEqual(detect_language("script.pyw"), "python")

    def test_unknown_extension_is_plaintext(self):
        self.assertEqual(detect_language("notes.txt"), "plaintext")
        self.assertEqual(detect_language("no_extension"), "plaintext")


class TestPythonTokenizer(unittest.TestCase):
    def test_keyword_detected(self):
        spans = tokenize("def foo():", "python")
        kinds = [s[2] for s in spans]
        self.assertIn("keyword", kinds)

    def test_string_detected(self):
        spans = tokenize('x = "hello"', "python")
        text_spans = [("string", "hello")]
        found = [s for s in spans if s[2] == "string"]
        self.assertTrue(found)
        start, end, _ = found[0]
        self.assertEqual('x = "hello"'[start:end], '"hello"')

    def test_comment_detected(self):
        spans = tokenize("x = 1  # a comment", "python")
        found = [s for s in spans if s[2] == "comment"]
        self.assertTrue(found)
        start, end, _ = found[0]
        self.assertEqual("x = 1  # a comment"[start:end], "# a comment")

    def test_number_detected(self):
        spans = tokenize("x = 42", "python")
        found = [s for s in spans if s[2] == "number"]
        self.assertEqual(len(found), 1)

    def test_comment_wins_over_keyword_inside_it(self):
        # 'if' appears inside the comment text but should stay tagged
        # as part of the comment, not split out as a keyword.
        line = "y = 2  # if this breaks, oops"
        spans = tokenize(line, "python")
        comment_spans = [s for s in spans if s[2] == "comment"]
        self.assertEqual(len(comment_spans), 1)
        start, end, _ = comment_spans[0]
        self.assertEqual(line[start:end], "# if this breaks, oops")

    def test_plaintext_returns_no_tokens(self):
        self.assertEqual(tokenize("anything at all", "plaintext"), [])

    def test_unknown_language_returns_no_tokens(self):
        self.assertEqual(tokenize("anything at all", "made_up_lang"), [])


if __name__ == "__main__":
    unittest.main()
