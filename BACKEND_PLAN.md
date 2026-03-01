# Command Center – Backend Plan

## SQL-schema

### `note_templates`
| Kolumn     | Typ          | Constraint              |
|------------|--------------|-------------------------|
| id         | VARCHAR(36)  | PRIMARY KEY             |
| user_id    | VARCHAR(36)  | NOT NULL, INDEX         |
| name       | VARCHAR(200) | NOT NULL                |
| skeleton   | TEXT         | nullable                |
| created_at | DATETIME     | NOT NULL, default NOW() |

### `cc_notes`
| Kolumn      | Typ          | Constraint                    |
|-------------|--------------|-------------------------------|
| id          | VARCHAR(36)  | PRIMARY KEY                   |
| user_id     | VARCHAR(36)  | NOT NULL, INDEX               |
| title       | VARCHAR(255) | NOT NULL, default ''          |
| content     | TEXT         | nullable                      |
| tags        | VARCHAR(500) | nullable, kommaseparerade     |
| template_id | VARCHAR(36)  | nullable, soft ref (ingen FK) |
| created_at  | DATETIME     | NOT NULL, default NOW()       |
| updated_at  | DATETIME     | NOT NULL, default NOW()       |

### `cc_todos`
| Kolumn      | Typ         | Constraint                    |
|-------------|-------------|-------------------------------|
| id          | VARCHAR(36) | PRIMARY KEY                   |
| user_id     | VARCHAR(36) | NOT NULL, INDEX               |
| content     | TEXT        | NOT NULL                      |
| type        | VARCHAR(10) | NOT NULL, 'week' eller 'date' |
| target_date | DATE        | nullable                      |
| week_number | INT         | nullable                      |
| status      | VARCHAR(20) | NOT NULL, 'open' eller 'done' |
| created_at  | DATETIME    | NOT NULL, default NOW()       |
| updated_at  | DATETIME    | NOT NULL, default NOW()       |

---

## Flask-endpoints (prefix: `/api/command-center`)

### Templates
| Method | Path                      | Beskrivning              |
|--------|---------------------------|--------------------------|
| GET    | `/templates`              | Lista alla templates      |
| POST   | `/templates`              | Skapa template            |
| PUT    | `/templates/<id>`         | Uppdatera template        |
| DELETE | `/templates/<id>`         | Ta bort template          |

### Notes
| Method | Path              | Beskrivning                         |
|--------|-------------------|-------------------------------------|
| GET    | `/notes`          | Lista alla notes (sorterade newest) |
| GET    | `/notes/<id>`     | Hämta enskild note                  |
| POST   | `/notes`          | Skapa note                          |
| PUT    | `/notes/<id>`     | Uppdatera note                      |
| DELETE | `/notes/<id>`     | Ta bort note                        |

### Todos
| Method | Path              | Beskrivning                                              |
|--------|-------------------|----------------------------------------------------------|
| GET    | `/todos`          | Lista todos; QS: `?type=week&week=12` / `?type=date&date=2025-03-15` |
| POST   | `/todos`          | Skapa todo                                               |
| PUT    | `/todos/<id>`     | Uppdatera todo                                           |
| DELETE | `/todos/<id>`     | Ta bort todo                                             |

---

## Nya filer
- `models/command_center_models.py` – SQLAlchemy-modeller
- `api/command_center_routes.py` – Blueprint `command_center_api`
- `migrations/versions/001_add_command_center_tables.py` – Alembic-migration
- `tests/test_command_center.py` – Lokalt testskript

## Ändringar i befintliga filer
- `app.py` – registrera blueprint + importera modeller
- `migrations/env.py` – importera `models.command_center_models`
