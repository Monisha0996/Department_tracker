from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes
import base64
# Generate a random 256-bit key
key = get_random_bytes(32)
# Create AES cipher in GCM mode
cipher = AES.new(key, AES.MODE_GCM)
nonce = cipher.nonce
# Encrypt data
data = b"Hi noel how are u today?"
ciphertext, tag = cipher.encrypt_and_digest(data)
# Decrypt data
cipher_dec = AES.new(key, AES.MODE_GCM, nonce=nonce)
plaintext = cipher_dec.decrypt_and_verify(ciphertext, tag)
print("Ciphertext:", base64.b64encode(ciphertext))
print("Decrypted:", plaintext.decode())