import os
import unittest

from cryptography.fernet import Fernet

from credential_crypto import KEY_ENVIRONMENT_VARIABLE, decrypt_password, rotate_password, store_password
from security_controls import rate_limit, redact_data, redact_secrets


class SecurityControlTests(unittest.TestCase):
    def setUp(self):
        self.original_key = os.environ.get(KEY_ENVIRONMENT_VARIABLE)
        os.environ[KEY_ENVIRONMENT_VARIABLE] = Fernet.generate_key().decode("ascii")

    def tearDown(self):
        if self.original_key is None:
            os.environ.pop(KEY_ENVIRONMENT_VARIABLE, None)
        else:
            os.environ[KEY_ENVIRONMENT_VARIABLE] = self.original_key

    def test_password_is_encrypted_and_key_rotation_preserves_it(self):
        details = {"password": "provider-secret"}
        store_password(details, details["password"])
        self.assertNotIn("password", details)
        self.assertNotIn("provider-secret", details["password_encrypted"])
        self.assertEqual("provider-secret", decrypt_password(details))
        old_key = os.environ[KEY_ENVIRONMENT_VARIABLE]
        new_key = Fernet.generate_key().decode("ascii")
        rotate_password(details, old_key, new_key)
        os.environ[KEY_ENVIRONMENT_VARIABLE] = new_key
        self.assertEqual("provider-secret", decrypt_password(details))

    def test_redacts_query_path_and_bearer_secrets(self):
        message = "Bearer abc.secret https://host/get.php?username=user&password=pass and http://host/live/user/pass/1.ts"
        redacted = redact_secrets(message)
        for secret in ("abc.secret", "username=user", "password=pass", "/user/pass/"):
            self.assertNotIn(secret, redacted)
        self.assertIn("[REDACTED]", redacted)
        payload = redact_data({"error": "https://host/get.php?password=pass", "password": "raw"})
        self.assertEqual("[REDACTED]", payload["password"])
        self.assertNotIn("password=pass", payload["error"])

    def test_rate_limit_rejects_excess_requests(self):
        key = "test-rate-limit-unique"
        self.assertTrue(rate_limit(key, 2, 60)[0])
        self.assertTrue(rate_limit(key, 2, 60)[0])
        allowed, retry_after = rate_limit(key, 2, 60)
        self.assertFalse(allowed)
        self.assertGreater(retry_after, 0)


if __name__ == "__main__":
    unittest.main()
