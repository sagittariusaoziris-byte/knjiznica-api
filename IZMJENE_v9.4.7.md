# Knjižnica API — Ispravci v9.4.7

## Problem
Klik na "Vrati knjigu" vraćao je `[500] Internal Server Error`.

## Uzrok (lanac bugova)

### Primarni bug — `return_loan` (loans.py)
Endpoint `POST /loans/{loan_id}/return` ima deklariran `response_model=LoanOut`,
ali je vraćao samo `{"id": loan_id, "is_returned": True}` — dict s 2 polja.

FastAPI pokušava validirati taj dict kroz `LoanOut` koji zahtijeva: `book_id`,
`member_id`, `loan_date`, `due_date`, `book`, `member`... → **500 ValidationError**.

### Sekundarni bug — Lazy load
Prethodni pokušaj da se vrati cijeli `LoanOut` pucao je jer SQLAlchemy
**lazy loading** pokušava učitati relacije (`book`, `member`) nakon što je
DB session već zatvoren → **500 DetachedInstanceError**.

### Sekundarni bug — `LoanReturn` schema
`LoanReturn` pydantic model nije imao `notes` polje, ali je `loans.py`
koristio `data.notes` → `AttributeError` u nekim slučajevima.

## Ispravci

### `app/routes/loans.py` (v9.3.0)
- Dodana helper funkcija `_loan_with_relations()` koja uvijek radi `joinedload`
  za `book` i `member` relacije
- `return_loan`: nakon `db.commit()` dohvaća posudbu s `_loan_with_relations()`
  i vraća validan `LoanOut` objekt (umjesto dict-a)
- `create_loan`: koristi `_loan_with_relations()` umjesto `db.refresh()`
- Uklonjeni debug endpointi `/debug/list` i `/debug/test`

### `app/schemas/schemas.py`
- `LoanReturn` dobiva `notes: Optional[str] = None`

### `app/main.py`
- Verzija bumped na `v9.4.7`

## Deployment
Samo zamijenite 3 fajla na serveru:
```
app/routes/loans.py
app/schemas/schemas.py
app/main.py
```
Restart servera je dovoljan — **nema migracija baze**.
