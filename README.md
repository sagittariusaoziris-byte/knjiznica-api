# 📚 Knjižnica API

REST API za upravljanje knjižnicom izgrađen s **FastAPI** i **SQLite**.

## Struktura projekta

```
library_api/
├── app/
│   ├── main.py           # Glavna aplikacija
│   ├── database.py       # Konekcija na bazu
│   ├── models/
│   │   └── models.py     # SQLAlchemy modeli (Book, Member, Loan, Reservation)
│   ├── schemas/
│   │   └── schemas.py    # Pydantic sheme za validaciju
│   └── routes/
│       ├── books.py      # /books endpoints
│       ├── members.py    # /members endpoints
│       ├── loans.py      # /loans endpoints
│       └── reservations.py # /reservations endpoints
├── requirements.txt
└── README.md
```

## Instalacija i pokretanje

```bash
# 1. Instaliraj ovisnosti
pip install -r requirements.txt

# 2. Pokreni server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## API Dokumentacija

Nakon pokretanja, otvori u browseru:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## Endpoints

### 📚 Knjige `/books`
| Metoda | URL | Opis |
|--------|-----|------|
| GET | `/books` | Lista svih knjiga (search, genre, available_only filteri) |
| GET | `/books/{id}` | Detalji knjige |
| POST | `/books` | Dodaj novu knjigu |
| PUT | `/books/{id}` | Uredi knjigu |
| DELETE | `/books/{id}` | Obriši knjigu |

### 👥 Članovi `/members`
| Metoda | URL | Opis |
|--------|-----|------|
| GET | `/members` | Lista članova (search, active_only) |
| GET | `/members/{id}` | Detalji člana |
| POST | `/members` | Registriraj novog člana |
| PUT | `/members/{id}` | Uredi člana |
| DELETE | `/members/{id}` | Obriši člana |

### 🔄 Posudbe `/loans`
| Metoda | URL | Opis |
|--------|-----|------|
| GET | `/loans` | Lista posudbi (filteri: member_id, book_id, active_only, overdue_only) |
| POST | `/loans` | Nova posudba |
| PATCH | `/loans/{id}/return` | Vrati knjigu |
| GET | `/loans/stats/overdue` | Sve prekoračene posudbe |

### 🔖 Rezervacije `/reservations`
| Metoda | URL | Opis |
|--------|-----|------|
| GET | `/reservations` | Lista rezervacija |
| POST | `/reservations` | Nova rezervacija |
| PATCH | `/reservations/{id}/cancel` | Otkaži rezervaciju |

### 📊 Status
| Metoda | URL | Opis |
|--------|-----|------|
| GET | `/` | Status servera |
| GET | `/stats` | Statistike (knjige, članovi, posudbe) |

## Primjeri korištenja

```bash
# Dodaj knjigu
curl -X POST http://localhost:8000/books \
  -H "Content-Type: application/json" \
  -d '{"title": "Zločin i kazna", "author": "Dostojevski", "year": 1866, "total_copies": 3}'

# Registriraj člana
curl -X POST http://localhost:8000/members \
  -H "Content-Type: application/json" \
  -d '{"first_name": "Ana", "last_name": "Horvat", "email": "ana@email.com"}'

# Posudi knjigu (loan_date + due_date)
curl -X POST http://localhost:8000/loans \
  -H "Content-Type: application/json" \
  -d '{"book_id": 1, "member_id": 1, "loan_date": "2025-01-01", "due_date": "2025-01-15"}'

# Vrati knjigu
curl -X PATCH http://localhost:8000/loans/1/return \
  -H "Content-Type: application/json" \
  -d '{"return_date": "2025-01-14"}'
```
