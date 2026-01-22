
from app.security import generate_api_key, hash_api_key, verify_api_key


class TestGenerateApiKey:
    def test_default_length(self):
        key = generate_api_key()
        assert len(key) == 64

    def test_custom_length(self):
        key = generate_api_key(length=32)
        assert len(key) == 32

    def test_produces_hex_string(self):
        key = generate_api_key()
        int(key, 16)

    def test_produces_unique_values(self):
        keys = [generate_api_key() for _ in range(100)]
        assert len(set(keys)) == 100


class TestHashApiKey:
    def test_produces_consistent_hash(self):
        key = "test_api_key_12345"
        hash1 = hash_api_key(key)
        hash2 = hash_api_key(key)
        assert hash1 == hash2

    def test_produces_sha256_length(self):
        key = "test_api_key"
        hashed = hash_api_key(key)
        assert len(hashed) == 64

    def test_different_inputs_produce_different_hashes(self):
        hash1 = hash_api_key("key_one")
        hash2 = hash_api_key("key_two")
        assert hash1 != hash2


class TestVerifyApiKey:
    def test_returns_true_for_matching_key(self):
        key = generate_api_key()
        key_hash = hash_api_key(key)
        assert verify_api_key(key, key_hash) is True

    def test_returns_false_for_non_matching_key(self):
        key = generate_api_key()
        key_hash = hash_api_key(key)
        wrong_key = generate_api_key()
        assert verify_api_key(wrong_key, key_hash) is False

    def test_returns_false_for_modified_hash(self):
        key = generate_api_key()
        key_hash = hash_api_key(key)
        first_char = key_hash[0]
        replacement = "1" if first_char == "0" else "0"
        modified_hash = replacement + key_hash[1:]
        assert verify_api_key(key, modified_hash) is False
