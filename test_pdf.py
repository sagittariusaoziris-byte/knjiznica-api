import requests

# 1. Dohvati token
r = requests.post('http://127.0.0.1:8000/auth/token', data={
    'username': 'admin_bugojno',
    'password': 'bugojno123'
})
token = r.json()['access_token']
print(f"Token: {token[:30]}...")

# 2. Testiraj PDF endpointove
headers = {'Authorization': f'Bearer {token}'}

endpoints = [
    '/pdf/books',
    '/pdf/members',
    '/pdf/loans',
    '/pdf/inventory',
    '/pdf/overdue-notices',
]

for endpoint in endpoints:
    r = requests.get(f'http://127.0.0.1:8000{endpoint}', headers=headers)
    ct = r.headers.get('content-type', '?')
    print(f"{endpoint}: {r.status_code} - {ct} - {len(r.content)} bytes")

# 3. Testiraj member-card
r = requests.get('http://127.0.0.1:8000/pdf/member-card/1', headers=headers)
ct = r.headers.get('content-type', '?')
print(f"/pdf/member-card/1: {r.status_code} - {ct} - {len(r.content)} bytes")

print("\nSvi testovi zavrseni!")
