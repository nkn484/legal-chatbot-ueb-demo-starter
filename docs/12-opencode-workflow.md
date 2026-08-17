# OpenCode Workflow

1. `python scripts/demo_gate.py start Mxx`
2. In OpenCode run `/mxx-...` (Plan agent).
3. Review the plan.
4. Switch to Build and say: `Implement the approved Mxx plan only. Do not start another milestone.`
5. Run `/review-milestone Mxx`.
6. `python scripts/demo_gate.py submit Mxx --note "..."`
7. USER approval: `python scripts/demo_gate.py approve Mxx --by USER --note "PASS for demo..."`

Rejection: `python scripts/demo_gate.py reject Mxx --by USER --note "..."`, then start again after fixing. No revision machinery.
