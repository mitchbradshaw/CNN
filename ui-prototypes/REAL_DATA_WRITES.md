# Files under the real DATA/ written or re-written during the prototyping task

Generated 2026-09-15 18:44 +1000 by comparing against `ui-prototypes/DATA_MTIMES_START.txt` (taken 2026-09-14 22:58 +10:00). Read-only inventory: nothing here has been deleted or modified by me after it was written. `DATA/db/annotations.sqlite` is unchanged (mtime and size equal the snapshot).

| mtime (local) | bytes | sha256 (first 16) | path | writer |
|---|---|---|---|---|
| 2026-09-15 17:35:07 | 260 | `d188306186bf4e06` | `DATA/derived/encodings/UNITTEST_encoding_view/CH00/sax_csax/51c72fd8.txt` | repo pytest (`tests/test_encoding_view*.py`) |
| 2026-09-15 17:35:12 | 260 | `f49ee102ca3ac2a0` | `DATA/derived/encodings/UNITTEST_encoding_view/CH00/sax_csax/643d2cbd.txt` | repo pytest (`tests/test_encoding_view*.py`) |
| 2026-09-15 17:34:49 | 300 | `eac93bb519e96f1d` | `DATA/derived/encodings/UNITTEST_encoding_view/CH00/sax_csax/64d04805.txt` | repo pytest (`tests/test_encoding_view*.py`) |
| 2026-09-15 17:34:26 | 300 | `eac93bb519e96f1d` | `DATA/derived/encodings/UNITTEST_encoding_view_dsax/CH00/sax_csax/64d04805.txt` | repo pytest (`tests/test_encoding_view*.py`) |
| 2026-09-15 17:34:31 | 300 | `f38c73d186596a4a` | `DATA/derived/encodings/UNITTEST_encoding_view_dsax/CH00/sax_dsax/c0c3bf2b.txt` | repo pytest (`tests/test_encoding_view*.py`) |
| 2026-09-14 23:05:59 | 13986 | `de3ee2a7bca7a1cc` | `DATA/derived/models/catalogue_classifier_153815b9dea451b2.joblib` | reader subagent executed `catalogue.classifier` directly (critique r1 P0) |
| 2026-09-15 17:34:55 | 244162 | `72efb24d54265c2e` | `DATA/derived/models/catalogue_classifier_16750c76ade64016.joblib` | repo pytest (classifier tests) |
| 2026-09-15 17:34:44 | 239522 | `121378d632e51e90` | `DATA/derived/models/catalogue_classifier_31895944e26935a4.joblib` | repo pytest (classifier tests) |
| 2026-09-15 17:34:58 | 238882 | `92f9005385b986d8` | `DATA/derived/models/catalogue_classifier_3d7fd04e0904dcc5.joblib` | repo pytest (classifier tests) |
| 2026-09-15 17:34:39 | 234002 | `60e5633456405651` | `DATA/derived/models/catalogue_classifier_ad10caaed29d1ad4.joblib` | repo pytest (classifier tests) |
| 2026-09-15 17:34:37 | 238930 | `634d2b455fe34486` | `DATA/derived/models/catalogue_classifier_f918586712c715e2.joblib` | repo pytest — **overwrote** a file that existed since 2026-09-04 |
| 2026-09-15 17:36:26 | 17385 | `400b3c75dd82cb21` | `DATA/derived/step_cache/0111ee82fdd4302165cda63db09acee06db7db2696161bdb6e9df05c09ee38d0/0/features.parquet` | repo pytest (`tests/test_step_cache.py`), same size as before — re-written |
| 2026-09-15 17:36:26 | 588 | `f9a14330174c7897` | `DATA/derived/step_cache/0111ee82fdd4302165cda63db09acee06db7db2696161bdb6e9df05c09ee38d0/0/windowset.npz` | repo pytest (`tests/test_step_cache.py`), same size as before — re-written |
| 2026-09-15 17:36:39 | 8575 | `0f5d2eaa4a2209a3` | `DATA/derived/step_cache/0a00dbd38655d9083fa3a375a43131a698ffd8744b773146784ca95ebaf99ae4/0/scores.npz` | repo pytest (`tests/test_step_cache.py`), same size as before — re-written |
| 2026-09-15 17:36:55 | 31295 | `75644a50d4afce4c` | `DATA/derived/step_cache/2a42e965b8a5c70d410f3c0a8e56cf342e9c1ba5b4c4d795bd5e1407899a02fb/0/scores.npz` | repo pytest (`tests/test_step_cache.py`), same size as before — re-written |
| 2026-09-15 17:36:35 | 1030 | `fae877e38d8edec3` | `DATA/derived/step_cache/bf50caf24febd94b8b8d57fb6434cadd370097266fe33fdfaf76afb6d696d9f9/0/scores.npz` | repo pytest (`tests/test_step_cache.py`), same size as before — re-written |

To remove only the files that did not exist before the task (leave the step_cache and the overwritten joblib in place, since those paths existed): delete the rows above whose writer is not 're-written' or 'overwrote'. I have not done this: removing anything under DATA/ is the user's call.
