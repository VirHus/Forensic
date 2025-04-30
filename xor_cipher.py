import hashlib

# Generate a fixed key using a passphrase
KEY = hashlib.sha256(b"your_static_passphrase").digest()

def xor_encrypt(data: bytes, key: bytes) -> bytes:
    """Encrypts data using XOR with a given key."""
    return bytes([data[i] ^ key[i % len(key)] for i in range(len(data))])

def xor_decrypt(data: bytes, key: bytes) -> bytes:
    """Decrypts data using XOR (same as encryption)."""
    return xor_encrypt(data, key)  # XOR decryption is identical to encryption
