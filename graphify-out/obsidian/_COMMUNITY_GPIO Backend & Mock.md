---
type: community
members: 13
---

# GPIO Backend & Mock

**Members:** 13 nodes

## Members
- [[.__init__()]] - code - plc_engine.py
- [[.__init__()_1]] - code - plc_engine.py
- [[._build_gpio()]] - code - plc_engine.py
- [[._make_input()]] - code - plc_engine.py
- [[._make_output()]] - code - plc_engine.py
- [[._make_pwm()]] - code - plc_engine.py
- [[.value()]] - code - plc_engine.py
- [[.value()_1]] - code - plc_engine.py
- [[Build inputoutput pin devices from project'gpio' (mirrors codegen.js]] - rationale - plc_engine.py
- [[Dependency-free stand-in for a gpiozero device (mirrors codegen _MockPin).]] - rationale - plc_engine.py
- [[Float-capable stand-in for a gpiozero PWMOutputDevice (duty 0.0..1.0).     Mirro]] - rationale - plc_engine.py
- [[_MockAnalog]] - code - plc_engine.py
- [[_MockPin]] - code - plc_engine.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/GPIO_Backend__Mock
SORT file.name ASC
```

## Connections to other communities
- 7 edges to [[_COMMUNITY_PLC Engine Core]]
- 1 edge to [[_COMMUNITY_Pi HTTP Runtime Server]]

## Top bridge nodes
- [[._build_gpio()]] - degree 9, connects to 2 communities
- [[_MockPin]] - degree 7, connects to 1 community
- [[_MockAnalog]] - degree 6, connects to 1 community
- [[._make_input()]] - degree 3, connects to 1 community
- [[._make_output()]] - degree 3, connects to 1 community