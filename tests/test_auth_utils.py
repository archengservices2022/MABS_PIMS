import hashlib
import unittest

from auth_utils import hash_password, password_needs_rehash, verify_password


class AuthUtilsTests(unittest.TestCase):
    def test_pbkdf2_hash_verifies_matching_password(self):
        stored = hash_password("correct horse battery staple")

        self.assertTrue(verify_password("correct horse battery staple", stored))
        self.assertFalse(verify_password("wrong password", stored))
        self.assertFalse(password_needs_rehash(stored))

    def test_legacy_sha256_hash_still_verifies_and_needs_rehash(self):
        stored = hashlib.sha256("legacy-password".encode("utf-8")).hexdigest()

        self.assertTrue(verify_password("legacy-password", stored))
        self.assertFalse(verify_password("wrong password", stored))
        self.assertTrue(password_needs_rehash(stored))

    def test_empty_hash_never_verifies(self):
        self.assertFalse(verify_password("anything", ""))


if __name__ == "__main__":
    unittest.main()
