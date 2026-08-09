import unittest

from dukkani_marketing.validation import next_status, validate_draft_input


class ValidationTests(unittest.TestCase):
    def test_valid_draft_is_normalized(self):
        self.assertEqual(validate_draft_input("  Title ", " Body ", "FACEBOOK"), {
            "title": "Title",
            "body": "Body",
            "channel": "facebook",
        })

    def test_invalid_channel_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported channel"):
            validate_draft_input("Title", "Body", "telegram")

    def test_empty_content_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_draft_input("", "Body", "internal")

    def test_approval_flow_is_explicit(self):
        self.assertEqual(next_status("Draft", "submit"), "Pending Approval")
        self.assertEqual(next_status("Pending Approval", "approve"), "Approved")

    def test_invalid_transition_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid content status transition"):
            next_status("Draft", "approve")


if __name__ == "__main__":
    unittest.main()
