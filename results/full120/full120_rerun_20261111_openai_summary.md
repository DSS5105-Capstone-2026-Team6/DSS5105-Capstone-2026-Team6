### Full-120 timeline rerun (rerun_20261111_openai)

Provider `openai`, stages on, periodic shocks (seed 5105), labels `data/f_heldout.json`.

- Behaviour accuracy: **93/120 = 0.775** (0 API errors: none)
- Workshop accuracy (allocate rows with a labelled shop): 0/0
- Mean latency: 7.5 s

| Expected behaviour | Correct |
|---|---|
| allocate | 49/52 |
| ask | 27/28 |
| impossible | 1/12 |
| no_data | 0/12 |
| refuse | 16/16 |

| Order named in the request | Requests | Correct |
|---|---|---|
| order COMPLETE in register | 86 | 62/86 (0.721) |
| order open in register | 34 | 31/34 (0.912) |

86 of the COMPLETE orders were completed after the request's sent date.

| Failure (expected -> got) | Count |
|---|---|
| no_data -> ask | 10 |
| impossible -> allocate | 8 |
| impossible -> ask | 3 |
| allocate -> refuse | 2 |
| ask -> allocate | 1 |
| no_data -> allocate | 1 |
| no_data -> answer | 1 |
| allocate -> ask | 1 |

| Request | Kind | Expected | Got | Order | Register status |
|---|---|---|---|---|---|
| F004 | unanswerable | no_data | ask | ORD-025 | COMPLETE |
| F008 | impossible | impossible | ask | ORD-117 | COMPLETE |
| F012 | impossible | impossible | allocate | ORD-049 | COMPLETE |
| F015 | missing | ask | allocate | ORD-028 | COMPLETE |
| F017 | impossible | impossible | allocate | ORD-115 | COMPLETE |
| F019 | impossible | impossible | allocate | ORD-001 | COMPLETE |
| F021 | impossible | impossible | allocate | ORD-089 | COMPLETE |
| F028 | unanswerable | no_data | ask | ORD-098 | COMPLETE |
| F031 | unanswerable | no_data | ask | ORD-102 | COMPLETE |
| F032 | unanswerable | no_data | allocate | ORD-006 | COMPLETE |
| F034 | unanswerable | no_data | ask | ORD-116 | COMPLETE |
| F039 | constraint | allocate | refuse | ORD-086 | COMPLETE |
| F040 | unanswerable | no_data | ask | ORD-022 | COMPLETE |
| F042 | unanswerable | no_data | answer | ORD-003 | COMPLETE |
| F048 | impossible | impossible | ask | ORD-058 | COMPLETE |
| F049 | unanswerable | no_data | ask | ORD-072 | COMPLETE |
| F052 | unanswerable | no_data | ask | ORD-042 | COMPLETE |
| F057 | unanswerable | no_data | ask | ORD-097 | COMPLETE |
| F060 | impossible | impossible | allocate | ORD-011 | COMPLETE |
| F061 | impossible | impossible | allocate | ORD-032 | COMPLETE |
| F062 | impossible | impossible | allocate | ORD-050 | COMPLETE |
| F070 | impossible | impossible | allocate | ORD-079 | COMPLETE |
| F082 | impossible | impossible | ask | ORD-019 | COMPLETE |
| F084 | constraint | allocate | refuse | ORD-114 | order open in register |
| F095 | complete | allocate | ask | ORD-060 | COMPLETE |
| F106 | unanswerable | no_data | ask | ORD-053 | order open in register |
| F107 | unanswerable | no_data | ask | ORD-073 | order open in register |
