# cqyi87 protocol baseline for PR1

Observed/captured Y1 PRO numeric protocol used by the clean upstream implementation:

| Function | Command / message | Data |
|---|---:|---|
| Start smart clean | `40001` | `{"cleanSwitch": true, "cleanMode": "smart"}` |
| Area clean | `40007` | `{"cleanSwitch": true, "cleanMode": "area", "cleanValues": [...]}` |
| Pause | `40009` | `{"pauseSwitch": true}` |
| Resume | `40011` | `{"pauseSwitch": false}` |
| Return to charger | `40013` | `{"chargeSwitch": true}` |
| Live state | `10000` | partial updates including `battery`, `status`, `pauseSwitch`, `chargeStatus`, `cleanArea`, `cleanTime` |
| Field query | `10001` | `{"fields": [...]}` |

State mapping:
- `status=smartClean` or `areaClean` -> cleaning
- `pauseSwitch=true` -> paused
- `status=goCharge` -> returning
- `chargeStatus=true` -> docked
- `status=idle` -> idle unless the same update explicitly establishes charging/docked state

Important PR1 rule: `10000` is a partial-update stream. A handler must not require all fields to be present and must not reset unrelated state when a field is omitted.

Physical-validation status should be stated conservatively in the upstream PR. Start smart cleaning is physically verified. Other captured commands should not be described as physically verified unless backed by an explicit test record.
