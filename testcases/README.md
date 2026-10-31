# E2E testcases

`testcases/<suite>/run_test.py`, run with `poetry run ./run_test_suite.sh <suite>`. Set
`FRONTEND_PORT` and `BACKEND_PORT` if 3000/8000 are taken, and point `DDNS_COLLECTIONS_ROOT` at a
scratch folder: the suite publishes into it.

| Suite | What it checks |
|-------|----------------|
| `studio_flow` | Say what a piece is for, get two takes that play, keep one, find it in the collection with its loop points, then change it into a new take. |
